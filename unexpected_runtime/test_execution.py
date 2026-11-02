from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import selectors
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Callable


class TestExecutionConfigurationError(ValueError):
    """Test executor configuration or profile is unsafe or incomplete."""


TEST_PROFILES: dict[str, dict[str, Any]] = {
    "evidence-engine": {
        "files": (
            "tests/test_evidence_engine.py",
            "unexpected_runtime/__init__.py",
            "unexpected_runtime/evidence.py",
            "unexpected_runtime/workflow.py",
        ),
        "argv": (
            "python",
            "-m",
            "unittest",
            "discover",
            "-s",
            "tests",
            "-p",
            "test_evidence_engine.py",
            "-v",
        ),
        "guest_timeout_seconds": 120,
        "trusted_files": {
            "tests/test_evidence_engine.py": "895bdd493ba846f2ac0c5bd8a67eeede5ef40b3c1862c17329ed1a87f907956e",
            "unexpected_runtime/__init__.py": "772770998e0dad14d84cfcb2a7f834855162ea025747d646864cd374322e00e6",
            "unexpected_runtime/evidence.py": "cacba534f92070722f6974c18354fe6308abddb8ff0eaaae486fbab0041ca02f",
            "unexpected_runtime/workflow.py": "f1dabd3cb4f283fef0200c0459e14b2fc0b9c8d240256e4aa8644b3003b38900",
        },
    }
}

_IMAGE_DIGEST = re.compile(r"^\S+@sha256:[0-9a-f]{64}$")
_SUMMARY = re.compile(r"(?m)^Ran ([0-9]+) tests? in [0-9.]+s\s*$")
_SUCCESS = re.compile(r"(?m)^OK(?: \([^\r\n]*\))?\s*$")


def _profile(criterion: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    profile_id = criterion.get("profile")
    if not isinstance(profile_id, str) or profile_id not in TEST_PROFILES:
        raise TestExecutionConfigurationError("A recognized fixed test profile is required.")
    return profile_id, TEST_PROFILES[profile_id]


_PROFILE_FILE_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def _profile_manifest(profile: dict[str, Any]) -> dict[str, str]:
    """Return the complete, canonical path-to-digest manifest for a fixed profile."""
    files = profile.get("files")
    trusted_files = profile.get("trusted_files")
    if (
        not isinstance(files, (tuple, list))
        or not files
        or any(not isinstance(path, str) or not path for path in files)
        or len(set(files)) != len(files)
        or not isinstance(trusted_files, dict)
        or set(trusted_files) != set(files)
    ):
        raise TestExecutionConfigurationError(
            "Every fixed test profile file must have exactly one pinned SHA-256 digest."
        )
    manifest: dict[str, str] = {}
    for relative in sorted(files):
        path = Path(relative)
        digest = trusted_files[relative]
        if path.is_absolute() or ".." in path.parts or not _PROFILE_FILE_DIGEST.fullmatch(digest if isinstance(digest, str) else ""):
            raise TestExecutionConfigurationError("The fixed test profile manifest is invalid.")
        manifest[relative] = digest
    return manifest


def _profile_manifest_sha256(profile: dict[str, Any]) -> str:
    data = json.dumps(_profile_manifest(profile), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _evidence_reference(scheme: str, actual: dict[str, Any]) -> str:
    """Bind provenance to the exact measured record and complete profile manifest."""
    data = json.dumps(actual, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return f"{scheme}://sha256/{hashlib.sha256(data.encode('utf-8')).hexdigest()}"


def _stage_profile(workspace_root: Path, profile: dict[str, Any]) -> tempfile.TemporaryDirectory[str]:
    manifest = _profile_manifest(profile)
    root = workspace_root.expanduser().resolve(strict=True)
    if not root.is_dir():
        raise TestExecutionConfigurationError("Test workspace root must be a directory.")
    staging = tempfile.TemporaryDirectory(prefix="unexpected-test-profile-")
    stage_root = Path(staging.name)
    stage_root.chmod(0o755)
    try:
        for relative in profile["files"]:
            source = root / relative
            current = root
            for component in Path(relative).parts:
                current = current / component
                if current.is_symlink():
                    raise TestExecutionConfigurationError("Fixed test profile paths cannot contain symlinks.")
            try:
                resolved = source.resolve(strict=True)
                resolved.relative_to(root)
            except (OSError, ValueError):
                raise TestExecutionConfigurationError("A fixed test profile file is missing or escapes the workspace.") from None
            if not resolved.is_file():
                raise TestExecutionConfigurationError("Fixed test profile files must be regular non-symlink files.")
            staged_bytes = resolved.read_bytes()
            if hashlib.sha256(staged_bytes).hexdigest() != manifest[relative]:
                raise TestExecutionConfigurationError("A pinned test profile file changed; review and update the trusted profile digest before execution.")
            destination = stage_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.parent.chmod(0o755)
            destination.write_bytes(staged_bytes)
            destination.chmod(0o644)
        return staging
    except BaseException:
        staging.cleanup()
        raise

def _bounded_output(stdout: Any, stderr: Any = "") -> str:
    def as_text(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    combined = as_text(stdout) + (("\n" + as_text(stderr)) if stderr else "")
    return combined[-12000:]


def _parse_result(output: str) -> tuple[int, bool]:
    summaries = list(_SUMMARY.finditer(output))
    if not summaries:
        return 0, False
    tests_run = int(summaries[-1].group(1))
    success = bool(_SUCCESS.search(output))
    return tests_run, success


def _run_bounded_process(argv: list[str], *, timeout_seconds: int,
                         max_output_bytes: int = 12000) -> tuple[int | None, str, bool]:
    """Drain a child incrementally and retain only a fixed-size output tail."""
    process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               bufsize=0, shell=False)
    if process.stdout is None:
        process.kill()
        process.wait(timeout=5)
        raise OSError("Could not open the test process output stream.")
    output = bytearray()
    timed_out = False
    selector = selectors.DefaultSelector()
    descriptor = process.stdout.fileno()
    os.set_blocking(descriptor, False)
    selector.register(descriptor, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout_seconds
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                timed_out = True
                if process.poll() is None:
                    process.kill()
                break
            for key, _ in selector.select(min(remaining, 0.2)):
                try:
                    chunk = os.read(key.fd, 4096)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fd)
                    continue
                output.extend(chunk)
                if len(output) > max_output_bytes:
                    del output[:-max_output_bytes]
        remaining = deadline - time.monotonic()
        try:
            exit_code = process.wait(timeout=max(0.0, remaining))
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            try:
                exit_code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                exit_code = None
    finally:
        selector.close()
        process.stdout.close()
    return exit_code, output.decode("utf-8", errors="replace"), timed_out


class DockerTestExecutor:
    """Run a named fixed test profile in a disposable, offline Docker container.

    This backend is intended for CI and explicitly configured self-hosted hosts.
    It requires an immutable image digest and never accepts a command from the task.
    """

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        image_digest: str,
        timeout_seconds: int = 180,
        docker_binary: str | None = None,
    ) -> None:
        if (
            not isinstance(image_digest, str)
            or not _IMAGE_DIGEST.fullmatch(image_digest)
            or image_digest.removeprefix("docker.io/library/").split("@", 1)[0].split(":", 1)[0] != "python"
        ):
            raise TestExecutionConfigurationError(
                "Docker test image must be the official Python image pinned by an immutable SHA-256 digest."
            )
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 30 <= timeout_seconds <= 600:
            raise TestExecutionConfigurationError("Docker test timeout must be between 30 and 600 seconds.")
        resolved_binary = docker_binary or shutil.which("docker")
        if not resolved_binary:
            raise TestExecutionConfigurationError("Docker is not installed or is unavailable on PATH.")
        self.workspace_root = Path(workspace_root)
        self.image_digest = image_digest
        self.timeout_seconds = timeout_seconds
        self.docker_binary = resolved_binary

    def __call__(self, candidate: Any, criterion: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        profile_id, profile = _profile(criterion)
        manifest = _profile_manifest(profile)
        manifest_sha256 = _profile_manifest_sha256(profile)
        staging = _stage_profile(self.workspace_root, profile)
        container_name = "unexpected-test-" + uuid.uuid4().hex[:20]
        argv = [
            self.docker_binary,
            "run",
            "--name", container_name,
            "--pull=never",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=64",
            "--memory=256m",
            "--cpus=1",
            "--user=65532:65532",
            "--tmpfs=/tmp:rw,nosuid,nodev,size=32m",
            "--mount", f"type=bind,source={staging.name},target=/workspace,readonly",
            "--workdir=/workspace",
            "--env=PYTHONDONTWRITEBYTECODE=1",
            "--env=PYTHONUNBUFFERED=1",
            self.image_digest,
            *profile["argv"],
        ]
        try:
            try:
                exit_code, output, timed_out = _run_bounded_process(
                    argv, timeout_seconds=self.timeout_seconds, max_output_bytes=12000,
                )
                tests_run, summary_passed = _parse_result(output)
            except (OSError, subprocess.TimeoutExpired):
                exit_code, output, timed_out = None, "", True
                tests_run, summary_passed = 0, False
            cleanup_confirmed = self._remove_container(container_name)
            passed = (
                not timed_out
                and type(exit_code) is int and exit_code == 0
                and tests_run > 0
                and summary_passed
                and cleanup_confirmed
            )
            actual = {
                "profile": profile_id,
                "executor": "docker",
                "test_profile_manifest": manifest,
                "test_profile_manifest_sha256": manifest_sha256,
                "exit_code": exit_code,
                "tests_run": tests_run,
                "status": "completed" if not timed_out else "timeout",
                "image_digest": self.image_digest,
                "isolation": {
                    "network": "none",
                    "read_only_root": True,
                    "non_root_user": "65532:65532",
                    "capabilities": "all_dropped",
                    "no_new_privileges": True,
                    "memory_limit": "256m",
                    "test_profile_sha256": profile["trusted_files"]["tests/test_evidence_engine.py"],
                    "cpu_limit": 1,
                    "pids_limit": 64,
                },
                "cleanup_confirmed": cleanup_confirmed,
                "output_tail": output[-4000:],
            }
            return {
                "passed": passed,
                "actual": actual,
                "expected": criterion.get("target", "all tests in the fixed profile pass"),
                "evidence_ref": _evidence_reference("docker-test", actual),
                "details": (
                    "Isolated Docker test profile executed with network disabled and bounded host-side output."
                    if passed else
                    "Docker test profile failed, timed out, returned no parsed unittest results, or cleanup was unconfirmed."
                ),
            }
        finally:
            staging.cleanup()

    def _remove_container(self, container_name: str) -> bool:
        try:
            cleaned = subprocess.run(
                [self.docker_binary, "rm", "-f", container_name],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
                shell=False,
            )
            return cleaned.returncode == 0 or "No such container" in (cleaned.stderr or "")
        except (OSError, subprocess.TimeoutExpired):
            return False


class RenderSandboxTestExecutor:
    """Execute the fixed profile in a disposable Render Sandbox microVM."""

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        workspace_id: str,
        token: str,
        timeout_seconds: int = 300,
        sandboxes: Any = None,
    ) -> None:
        if not isinstance(workspace_id, str) or not workspace_id.strip():
            raise TestExecutionConfigurationError("RENDER_WORKSPACE_ID is required for Render Sandboxes.")
        if not isinstance(token, str) or not token.strip():
            raise TestExecutionConfigurationError("RENDER_API_KEY is required for Render Sandboxes.")
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int) or not 60 <= timeout_seconds <= 600:
            raise TestExecutionConfigurationError("Render Sandbox timeout must be between 60 and 600 seconds.")
        self.workspace_root = Path(workspace_root)
        self.workspace_id = workspace_id
        self._token = token
        self.timeout_seconds = timeout_seconds
        self._sandboxes = sandboxes

    def _client(self) -> Any:
        if self._sandboxes is not None:
            return self._sandboxes
        try:
            from render import RenderAsync
        except ImportError:
            raise TestExecutionConfigurationError("The pinned Render Python SDK is not installed.") from None
        return RenderAsync(token=self._token, owner_id=self.workspace_id).sandboxes

    def __call__(self, candidate: Any, criterion: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        _profile(criterion)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._execute(criterion))
        raise TestExecutionConfigurationError("Render Sandbox adapter must be called from a synchronous lifecycle worker.")

    async def _execute(self, criterion: dict[str, Any]) -> dict[str, Any]:
        profile_id, profile = _profile(criterion)
        manifest = _profile_manifest(profile)
        manifest_sha256 = _profile_manifest_sha256(profile)
        sandboxes = self._client()
        staging = _stage_profile(self.workspace_root, profile)
        sandbox_id = None
        output_parts: list[str] = []
        exit_code: int | None = None
        timed_out = False
        cleanup_confirmed = False
        failure: str | None = None
        guest_timeout = min(profile["guest_timeout_seconds"], self.timeout_seconds - 30)
        command = (
            f"cd /workspace && timeout -k 2 {guest_timeout} "
            "python3 -m unittest discover -s tests -p test_evidence_engine.py -v"
        )
        try:
            sandbox = await sandboxes.create(
                timeout_seconds=self.timeout_seconds,
                idle_timeout_seconds=300,
                network_policy="deny-all",
            )
            sandbox_id = sandbox.id
            await sandboxes.wait_until_running(
                sandbox_id,
                timeout_seconds=min(90, self.timeout_seconds - 30),
                interval_seconds=0.5,
            )
            await sandboxes.copy_to(sandbox_id, staging.name, "/workspace")

            async def collect() -> None:
                nonlocal exit_code
                async for event in sandboxes.exec(sandbox_id, command):
                    if hasattr(event, "exit_code"):
                        exit_code = event.exit_code
                    elif hasattr(event, "data"):
                        output_parts.append(str(event.data)[-12000:])
                        # Retain a strict output budget in the host.
                        while sum(len(part) for part in output_parts) > 12000:
                            output_parts.pop(0)

            try:
                await asyncio.wait_for(collect(), timeout=guest_timeout + 10)
            except asyncio.TimeoutError:
                timed_out = True
                failure = "sandbox execution stream exceeded its bounded deadline"
            if exit_code is None:
                timed_out = True
                failure = failure or "sandbox stream ended without an exit event"
        except Exception as exc:
            sandbox_id = sandbox_id or getattr(exc, "sandbox_id", None)
            failure = f"Render Sandbox operation failed: {type(exc).__name__}"
        finally:
            if sandbox_id is not None:
                try:
                    await asyncio.wait_for(sandboxes.terminate(sandbox_id), timeout=15)
                    cleanup_confirmed = True
                except Exception:
                    cleanup_confirmed = False
            staging.cleanup()

        output = "".join(output_parts)[-12000:]
        tests_run, summary_passed = _parse_result(output)
        passed = (
            failure is None
            and not timed_out
            and type(exit_code) is int and exit_code == 0
            and tests_run > 0
            and summary_passed
            and cleanup_confirmed
        )
        actual = {
            "profile": profile_id,
            "executor": "render-sandbox",
            "test_profile_manifest": manifest,
            "test_profile_manifest_sha256": manifest_sha256,
            "sandbox_id": sandbox_id,
            "exit_code": exit_code,
            "tests_run": tests_run,
            "status": "completed" if not timed_out and failure is None else "failed",
            "network_policy": "deny-all",
            "test_profile_sha256": profile["trusted_files"]["tests/test_evidence_engine.py"],
            "cleanup_confirmed": cleanup_confirmed,
            "output_tail": output[-4000:],
        }
        return {
            "passed": passed,
            "actual": actual,
            "expected": criterion.get("target", "all tests in the fixed profile pass"),
            "evidence_ref": _evidence_reference("render-sandbox", actual),
            "details": failure or (
                "Isolated Render Sandbox test profile completed with network egress denied."
                if passed else
                "Render Sandbox test profile failed, timed out, returned no parsed unittest results, or cleanup was unconfirmed."
            ),
        }


class TestEvidenceChecker:
    """Adapt an executor's measured result into the evidence engine contract."""

    def __init__(self, executor: Callable[[Any, dict[str, Any], dict[str, Any]], dict[str, Any]]) -> None:
        if not callable(executor):
            raise TestExecutionConfigurationError("Test executor must be callable.")
        self.executor = executor

    def __call__(
        self,
        candidate: Any,
        criterion: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        result = self.executor(candidate, criterion, context)
        if not isinstance(result, dict):
            raise TestExecutionConfigurationError("Test executor returned an invalid result.")
        _, profile = _profile(criterion)
        expected_manifest = _profile_manifest(profile)
        expected_manifest_sha256 = _profile_manifest_sha256(profile)
        actual = result.get("actual")
        manifest_verified = (
            isinstance(actual, dict)
            and actual.get("test_profile_manifest") == expected_manifest
            and actual.get("test_profile_manifest_sha256") == expected_manifest_sha256
        )
        executor_id = actual.get("executor") if isinstance(actual, dict) else None
        expected_scheme = {"docker": "docker-test", "render-sandbox": "render-sandbox"}.get(executor_id)
        evidence_ref = result.get("evidence_ref")
        reference_verified = (
            expected_scheme is not None and isinstance(evidence_ref, str)
            and evidence_ref == _evidence_reference(expected_scheme, actual)
        )
        passed = (
            result.get("passed") is True and isinstance(actual, dict)
            and manifest_verified and reference_verified
            and type(actual.get("exit_code")) is int and actual.get("exit_code") == 0
            and isinstance(actual.get("tests_run"), int) and not isinstance(actual.get("tests_run"), bool)
            and actual.get("tests_run") > 0 and actual.get("cleanup_confirmed") is True
            and actual.get("status") == "completed"
        )
        if not isinstance(evidence_ref, str) or not evidence_ref.strip():
            raise TestExecutionConfigurationError("Test executor did not return a provenance reference.")
        return {
            "passed": passed,
            "actual": actual,
            "expected": criterion["target"],
            "evidence_ref": evidence_ref,
            "details": str(result.get("details") or ""),
        }


def test_executor_from_env(workspace_root: str | Path | None = None) -> DockerTestExecutor | RenderSandboxTestExecutor | None:
    backend = os.getenv("UNEXPECTED_TEST_EXECUTOR", "").strip().lower()
    if not backend:
        return None
    root = Path(
        workspace_root
        or os.getenv("UNEXPECTED_TEST_WORKSPACE_ROOT")
        or Path(__file__).resolve().parents[1]
    )
    timeout = int(os.getenv("UNEXPECTED_TEST_TIMEOUT_SECONDS", "180"))
    if backend == "docker":
        return DockerTestExecutor(
            root,
            image_digest=os.getenv("UNEXPECTED_TEST_DOCKER_IMAGE", ""),
            timeout_seconds=timeout,
        )
    if backend == "render-sandbox":
        timeout = int(os.getenv("UNEXPECTED_TEST_SANDBOX_TIMEOUT_SECONDS", "300"))
        return RenderSandboxTestExecutor(
            root,
            workspace_id=os.getenv("RENDER_WORKSPACE_ID", ""),
            token=os.getenv("RENDER_API_KEY", ""),
            timeout_seconds=timeout,
        )
    raise TestExecutionConfigurationError("UNEXPECTED_TEST_EXECUTOR must be docker or render-sandbox.")
