from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
import json
import math
import os
import selectors
import signal
import subprocess
import time


class IsolationError(RuntimeError):
    """The worker container could not prove or maintain its isolation contract."""


@dataclass(frozen=True)
class PodmanIsolationConfig:
    podman_path: Path
    image: str
    xdg_runtime_dir: Path | None = None
    node_path: str = "/usr/local/bin/node"
    ffmpeg_path: str = "/usr/bin/ffmpeg"
    ffprobe_path: str = "/usr/bin/ffprobe"
    runner_path: str = "/opt/uneXpected-openfilm/run-job.mjs"
    container_uid: str = "10001:10001"
    max_memory_bytes: int = 3 * 1024 * 1024 * 1024
    max_cpu_limit: float = 1.5
    max_pids: int = 128
    tmpfs_bytes: int = 1024 * 1024 * 1024
    max_stdout_bytes: int = 32 * 1024
    max_stderr_bytes: int = 32 * 1024

    def __post_init__(self):
        executable = Path(self.podman_path)
        if not executable.is_absolute():
            raise ValueError("podman_path must be absolute.")
        if not self.image or "@sha256:" not in self.image:
            raise ValueError("Worker image must be pinned by a sha256 digest.")
        digest = self.image.rsplit("@sha256:", 1)[-1]
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("Worker image digest must be a lowercase SHA-256 value.")
        for name, value in (
            ("node_path", self.node_path), ("ffmpeg_path", self.ffmpeg_path),
            ("ffprobe_path", self.ffprobe_path), ("runner_path", self.runner_path),
        ):
            if not isinstance(value, str) or not value.startswith("/") or ".." in Path(value).parts:
                raise ValueError(f"{name} must be a fixed absolute container path.")
        if self.container_uid != "10001:10001":
            raise ValueError("The media worker container must run as the fixed unprivileged UID 10001.")
        for name, value in (
            ("max_memory_bytes", self.max_memory_bytes),
            ("max_pids", self.max_pids),
            ("tmpfs_bytes", self.tmpfs_bytes),
            ("max_stdout_bytes", self.max_stdout_bytes),
            ("max_stderr_bytes", self.max_stderr_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer.")
        if isinstance(self.max_cpu_limit, bool) or not math.isfinite(float(self.max_cpu_limit)) or self.max_cpu_limit <= 0:
            raise ValueError("max_cpu_limit must be finite and positive.")


@dataclass(frozen=True)
class WorkerResourceLimits:
    memory_bytes: int
    cpu_limit: float
    pids_limit: int
    tmpfs_bytes: int
    max_output_bytes: int
    max_stdout_bytes: int = 16 * 1024
    max_stderr_bytes: int = 16 * 1024

    def validate(self, config: PodmanIsolationConfig) -> None:
        values = (
            self.memory_bytes, self.pids_limit, self.tmpfs_bytes,
            self.max_output_bytes, self.max_stdout_bytes, self.max_stderr_bytes,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in values):
            raise ValueError("Worker resource limits must be positive integers.")
        if not math.isfinite(float(self.cpu_limit)) or self.cpu_limit <= 0:
            raise ValueError("Worker CPU limit must be finite and positive.")
        if self.memory_bytes > config.max_memory_bytes or self.cpu_limit > config.max_cpu_limit:
            raise ValueError("Job resource request exceeds the host's configured isolation ceiling.")
        if self.pids_limit > config.max_pids or self.tmpfs_bytes > config.tmpfs_bytes:
            raise ValueError("Job process or temporary-storage limit exceeds the host ceiling.")
        if self.max_stdout_bytes > config.max_stdout_bytes or self.max_stderr_bytes > config.max_stderr_bytes:
            raise ValueError("Job diagnostic limit exceeds the host ceiling.")


class PodmanIsolation:
    """Rootless, network-denied, no-shell OpenFilm container executor."""

    def __init__(self, config: PodmanIsolationConfig):
        self.config = config

    def _env(self) -> dict[str, str]:
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/tmp",
            "TMPDIR": "/tmp",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        if self.config.xdg_runtime_dir is not None:
            env["XDG_RUNTIME_DIR"] = str(self.config.xdg_runtime_dir)
        return env

    @staticmethod
    def _run(command: list[str], *, env: dict[str, str], timeout: float = 8.0) -> subprocess.CompletedProcess:
        return subprocess.run(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, timeout=timeout,
            check=False, shell=False, env=env,
        )

    def _base_run_args(self, limits: WorkerResourceLimits) -> list[str]:
        return [
            str(self.config.podman_path), "run", "--rm",
            "--network=none", "--read-only", "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit", str(limits.pids_limit),
            "--memory", str(limits.memory_bytes),
            "--cpus", str(limits.cpu_limit),
            "--user", self.config.container_uid,
            "--tmpfs", f"/tmp:rw,nosuid,nodev,size={limits.tmpfs_bytes}",
        ]

    def self_test(self) -> dict[str, Any]:
        try:
            executable = self.config.podman_path
            if not executable.is_file() or not os.access(executable, os.X_OK):
                return {"available": False, "reason": "Configured Podman executable is missing or not executable."}
            version = self._run([str(executable), "--version"], env=self._env())
            if version.returncode != 0 or "podman" not in version.stdout.lower():
                return {"available": False, "reason": "Podman version check failed."}
            info = self._run([str(executable), "info", "--format", "json"], env=self._env(), timeout=12)
            if info.returncode != 0:
                return {"available": False, "reason": "Podman host information could not be read."}
            payload = json.loads(info.stdout)
            host = payload.get("host", {})
            security = host.get("security", {}) if isinstance(host, dict) else {}
            if security.get("rootless") is not True:
                return {"available": False, "reason": "Podman is not running rootless."}
            cgroup_version = str(host.get("cgroupVersion", "")) if isinstance(host, dict) else ""
            if cgroup_version not in {"v2", "2"}:
                return {"available": False, "reason": "Host cgroup v2 is required to enforce CPU, memory and PID limits."}
            digest = self.config.image.rsplit("@", 1)[1]
            inspect = self._run(
                [str(executable), "image", "inspect", "--format", "{{.Digest}}", self.config.image],
                env=self._env(),
            )
            if inspect.returncode != 0 or inspect.stdout.strip() != digest:
                return {"available": False, "reason": "Digest-pinned OpenFilm worker image is not present or does not match."}
            probe_script = (
                "const {spawnSync}=require('node:child_process');"
                "if(typeof process.getuid!=='function'||process.getuid()===0)process.exit(11);"
                "for(const p of ['/usr/bin/ffmpeg','/usr/bin/ffprobe']){"
                "const r=spawnSync(p,['-version'],{stdio:'ignore'});if(r.error||r.status!==0)process.exit(12);}"
                "const net=require('node:net');const s=net.connect({host:'1.1.1.1',port:443});"
                "s.setTimeout(1200);s.on('connect',()=>process.exit(13));"
                "s.on('error',()=>{console.log('isolated');process.exit(0)});"
                "s.on('timeout',()=>{s.destroy();console.log('isolated');process.exit(0)});"
            )
            probe_args = self._base_run_args(WorkerResourceLimits(
                memory_bytes=min(128 * 1024 * 1024, self.config.max_memory_bytes),
                cpu_limit=min(0.25, self.config.max_cpu_limit),
                pids_limit=min(16, self.config.max_pids),
                tmpfs_bytes=min(32 * 1024 * 1024, self.config.tmpfs_bytes),
                max_output_bytes=1024,
            ))
            probe_args.extend([
                self.config.image, self.config.node_path, "-e", probe_script,
            ])
            probe = self._run(probe_args, env=self._env(), timeout=15)
            if probe.returncode != 0 or "isolated" not in probe.stdout:
                return {"available": False, "reason": "Container probe did not prove non-root execution, FFmpeg tools and network denial."}
            return {
                "available": True,
                "podman_version": version.stdout.strip()[:120],
                "image": self.config.image,
                "rootless": True,
                "cgroup_version": "v2",
                "network": "none",
                "resource_limits": "verified by container probe",
            }
        except (OSError, subprocess.TimeoutExpired, ValueError, TypeError, json.JSONDecodeError):
            return {"available": False, "reason": "Podman isolation self-test failed closed."}

    def build_command(
        self, project_root: str | Path, attempt_root: str | Path,
        request: dict[str, Any], limits: WorkerResourceLimits,
    ) -> tuple[list[str], dict[str, Any]]:
        limits.validate(self.config)
        project = Path(project_root).resolve(strict=True)
        attempt = Path(attempt_root).resolve(strict=True)
        job_dir = attempt.parent
        job_id = job_dir.name
        attempt_id = attempt.name
        container_attempt = f"/artifacts/{job_id}/{attempt_id}"
        container_request = {
            "job_id": request["job_id"],
            "project_root": "/source",
            "entrypoint": "film.html",
            "artifact_root": "/artifacts",
            "attempt_root": container_attempt,
            "output_path": f"{container_attempt}/master.mp4",
            "profile": request["profile"],
            "max_output_bytes": limits.max_output_bytes,
        }
        command = self._base_run_args(limits)
        command.extend([
            "--mount", f"type=bind,src={project},dst=/source,ro=true,rprivate",
            "--mount", f"type=bind,src={job_dir},dst=/artifacts/{job_id},rw=true,rprivate",
            self.config.image,
            self.config.node_path,
            self.config.runner_path,
        ])
        return command, container_request

    @staticmethod
    def _terminate(proc: subprocess.Popen) -> None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=2)

    def run_fixed_runner(
        self, request: dict[str, Any], project_root: str | Path, attempt_root: str | Path,
        limits: WorkerResourceLimits, timeout_seconds: float,
        *, on_phase: Callable[[str], None], cancel_check: Callable[[], bool],
    ) -> dict[str, Any]:
        if not math.isfinite(float(timeout_seconds)) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive.")
        command, container_request = self.build_command(project_root, attempt_root, request, limits)
        process = subprocess.Popen(
            command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=False, env=self._env(), start_new_session=True, bufsize=0,
        )
        assert process.stdin is not None and process.stdout is not None and process.stderr is not None
        request_bytes = (json.dumps(container_request, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
        if len(request_bytes) > 32 * 1024:
            self._terminate(process)
            raise IsolationError("Runner request exceeded the fixed JSON input limit.")
        try:
            process.stdin.write(request_bytes)
            process.stdin.close()
        except OSError:
            self._terminate(process)
            raise IsolationError("Runner request could not be dispatched.") from None

        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        stdout_buffer = bytearray()
        stderr_buffer = bytearray()
        stdout_total = 0
        stderr_total = 0
        result = None
        deadline = time.monotonic() + float(timeout_seconds)
        cancelled = False
        try:
            while selector.get_map() or process.poll() is None:
                if cancel_check():
                    cancelled = True
                    self._terminate(process)
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._terminate(process)
                    raise IsolationError("OpenFilm container exceeded its configured wall-time limit.")
                for key, _ in selector.select(min(0.25, remaining)):
                    chunk = os.read(key.fileobj.fileno(), 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if key.data == "stdout":
                        stdout_total += len(chunk)
                        if stdout_total > limits.max_stdout_bytes:
                            self._terminate(process)
                            raise IsolationError("OpenFilm container exceeded its stdout byte limit.")
                        stdout_buffer.extend(chunk)
                        while b"\n" in stdout_buffer:
                            raw, _, rest = stdout_buffer.partition(b"\n")
                            stdout_buffer[:] = rest
                            try:
                                event = json.loads(raw.decode("utf-8"))
                            except (UnicodeDecodeError, json.JSONDecodeError):
                                self._terminate(process)
                                raise IsolationError("OpenFilm runner emitted invalid JSON Lines.") from None
                            if event.get("event") == "phase":
                                phase = event.get("phase")
                                if phase not in {"inspecting", "rendering"}:
                                    self._terminate(process)
                                    raise IsolationError("OpenFilm runner emitted an unknown phase.")
                                on_phase(phase)
                            elif event.get("event") == "result" and isinstance(event.get("result"), dict):
                                result = event["result"]
                            else:
                                self._terminate(process)
                                raise IsolationError("OpenFilm runner emitted an unknown response event.")
                    else:
                        stderr_total += len(chunk)
                        if stderr_total > limits.max_stderr_bytes:
                            self._terminate(process)
                            raise IsolationError("OpenFilm container exceeded its stderr byte limit.")
                        stderr_buffer.extend(chunk)
                if process.poll() is not None and not selector.get_map():
                    break
            if cancelled:
                return {"status": "cancelled", "failure_category": "cancelled"}
            return_code = process.wait(timeout=2)
            if stdout_buffer.strip():
                try:
                    event = json.loads(stdout_buffer.decode("utf-8"))
                    if event.get("event") == "result" and isinstance(event.get("result"), dict):
                        result = event["result"]
                    else:
                        raise ValueError
                except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
                    raise IsolationError("OpenFilm runner returned an incomplete JSON event.") from None
            if return_code not in {0, 2, 3, 1} or result is None:
                raise IsolationError("OpenFilm container exited without a valid result.")
            return result
        finally:
            selector.close()
            if process.poll() is None:
                self._terminate(process)
