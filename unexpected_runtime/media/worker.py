from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
import json
import math
import os
import shutil
import time

from .isolation import WorkerResourceLimits
from .paths import MediaPathError, MediaPathPolicy
from .jobs import MediaJobService
from .manifest import MediaManifest


class MediaWorkerError(RuntimeError):
    """A media worker could not safely complete its one-job operation."""


@dataclass(frozen=True)
class MediaWorkerConfig:
    worker_id: str
    project_root: Path
    artifact_root: Path
    timeout_seconds: float
    lease_seconds: float
    max_project_bytes: int
    max_asset_count: int
    max_file_bytes: int
    max_output_bytes: int
    memory_bytes: int
    cpu_limit: float
    pids_limit: int
    tmpfs_bytes: int

    def __post_init__(self):
        if not isinstance(self.worker_id, str) or not self.worker_id.strip():
            raise ValueError("worker_id is required.")
        for name, path in (("project_root", self.project_root), ("artifact_root", self.artifact_root)):
            if not Path(path).is_absolute():
                raise ValueError(f"{name} must be an absolute path.")
        for name, value in (
            ("max_project_bytes", self.max_project_bytes),
            ("max_asset_count", self.max_asset_count),
            ("max_file_bytes", self.max_file_bytes),
            ("max_output_bytes", self.max_output_bytes),
            ("memory_bytes", self.memory_bytes),
            ("pids_limit", self.pids_limit),
            ("tmpfs_bytes", self.tmpfs_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer.")
        for name, value in (("timeout_seconds", self.timeout_seconds), ("lease_seconds", self.lease_seconds), ("cpu_limit", self.cpu_limit)):
            if isinstance(value, bool) or not math.isfinite(float(value)) or float(value) <= 0:
                raise ValueError(f"{name} must be finite and positive.")
        if self.max_file_bytes > self.max_project_bytes:
            raise ValueError("max_file_bytes cannot exceed max_project_bytes.")
        if self.timeout_seconds > self.lease_seconds - 10:
            raise ValueError("lease_seconds must exceed timeout_seconds by at least 10 seconds.")

    @classmethod
    def from_env(cls) -> "MediaWorkerConfig":
        def required(name: str) -> str:
            value = os.environ.get(name, "").strip()
            if not value:
                raise MediaWorkerError(f"Required worker setting {name} is not configured.")
            return value

        def integer(name: str) -> int:
            try:
                return int(required(name))
            except ValueError:
                raise MediaWorkerError(f"Worker setting {name} must be an integer.") from None

        def number(name: str) -> float:
            try:
                return float(required(name))
            except ValueError:
                raise MediaWorkerError(f"Worker setting {name} must be a number.") from None

        return cls(
            worker_id=required("UNEXPECTED_OPENFILM_WORKER_ID"),
            project_root=Path(required("UNEXPECTED_OPENFILM_PROJECT_ROOT")),
            artifact_root=Path(required("UNEXPECTED_OPENFILM_ARTIFACT_ROOT")),
            timeout_seconds=number("UNEXPECTED_OPENFILM_TIMEOUT_SECONDS"),
            lease_seconds=number("UNEXPECTED_OPENFILM_LEASE_SECONDS"),
            max_project_bytes=integer("UNEXPECTED_OPENFILM_MAX_PROJECT_BYTES"),
            max_asset_count=integer("UNEXPECTED_OPENFILM_MAX_ASSET_COUNT"),
            max_file_bytes=integer("UNEXPECTED_OPENFILM_MAX_FILE_BYTES"),
            max_output_bytes=integer("UNEXPECTED_OPENFILM_MAX_OUTPUT_BYTES"),
            memory_bytes=integer("UNEXPECTED_OPENFILM_MEMORY_BYTES"),
            cpu_limit=number("UNEXPECTED_OPENFILM_CPU_LIMIT"),
            pids_limit=integer("UNEXPECTED_OPENFILM_PIDS_LIMIT"),
            tmpfs_bytes=integer("UNEXPECTED_OPENFILM_TMPFS_BYTES"),
        )


class MediaWorker:
    """Claims, processes and exits after at most one media job."""

    def __init__(self, jobs: MediaJobService, isolation, config: MediaWorkerConfig, *, qa=None):
        self.jobs = jobs
        self.isolation = isolation
        self.config = config
        self.qa = qa
        self.paths = MediaPathPolicy(
            artifact_root=config.artifact_root,
            max_project_bytes=config.max_project_bytes,
            max_asset_count=config.max_asset_count,
            max_file_bytes=config.max_file_bytes,
        )

    def _limits(self) -> WorkerResourceLimits:
        return WorkerResourceLimits(
            memory_bytes=self.config.memory_bytes,
            cpu_limit=self.config.cpu_limit,
            pids_limit=self.config.pids_limit,
            tmpfs_bytes=self.config.tmpfs_bytes,
            max_output_bytes=self.config.max_output_bytes,
        )

    @staticmethod
    def _project_directory(value: Any) -> str:
        if not isinstance(value, str) or not value.strip() or "\\" in value:
            raise MediaPathError("Job project_path must be a relative project directory or film.html path.")
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in {"", ".", ".."} or part.startswith(".") for part in path.parts):
            raise MediaPathError("Job project_path contains unsafe path components.")
        if path.parts[-1] == "film.html":
            parent = path.parts[:-1]
            if not parent:
                raise MediaPathError("Project film.html must be inside a named project directory.")
            path = PurePosixPath(*parent)
        return path.as_posix()

    def _state_change(self, job, current_state: str, target_state: str, result=None) -> bool:
        return self.jobs.advance(
            job["job_id"],
            expected_state=current_state,
            target_state=target_state,
            worker_id=self.config.worker_id,
            lease_token=job["lease_token"],
            result=result,
        )

    def _finish_failure(self, job, state: str, category: str, message: str) -> dict[str, Any]:
        current = self.jobs.get(job["job_id"])
        if current and current["state"] == "cancel_requested":
            self.jobs.advance(
                job["job_id"], expected_state="cancel_requested", target_state="cancelled",
                worker_id=self.config.worker_id, lease_token=job["lease_token"],
                result={"failure_category": "cancelled"},
            )
            return {"job_id": job["job_id"], "status": "cancelled"}
        if state not in {"claimed", "inspecting", "rendering", "post_render_qa", "cancel_requested"}:
            state = current["state"] if current else state
        self.jobs.advance(
            job["job_id"], expected_state=state, target_state="failed",
            worker_id=self.config.worker_id, lease_token=job["lease_token"],
            result={"failure_category": category, "message": message[:300]},
        )
        return {"job_id": job["job_id"], "status": "failed", "failure_category": category}

    def run_once(self) -> dict[str, Any]:
        readiness = self.isolation.self_test()
        if not isinstance(readiness, dict) or readiness.get("available") is not True:
            reason = readiness.get("reason") if isinstance(readiness, dict) else None
            return {
                "status": "unavailable",
                "reason": reason or "Worker isolation self-test has not passed.",
                "claimed": False,
            }
        try:
            limits = self._limits()
            validate_limits = getattr(self.isolation, "validate_limits", None)
            if callable(validate_limits):
                validate_limits(limits)
        except Exception as exc:
            return {"status": "unavailable", "reason": f"Worker limits are not enforceable ({type(exc).__name__}).", "claimed": False}

        job = self.jobs.claim_one(self.config.worker_id, lease_seconds=self.config.lease_seconds)
        if job is None:
            return {"status": "idle", "claimed": False}
        state = "claimed"
        try:
            request = json.loads(job["request_json"])
            project_relative = self._project_directory(request.get("project_path"))
            snapshot = self.paths.inspect_project(self.config.project_root, project_relative)
            variants = request.get("variants")
            if not isinstance(variants, list) or len(variants) != 1 or not isinstance(variants[0], dict):
                return self._finish_failure(job, state, "invalid_variant_count", "Each media job must contain exactly one render variant.")
            profile = variants[0]
            renderer_profile = {
                "platform": profile.get("platform"),
                "width": profile.get("width"),
                "height": profile.get("height"),
                "fps": profile.get("fps"),
                "audio_required": profile.get("audio_required", False),
            }
            attempt_root = self.paths.prepare_attempt(job["job_id"], job["attempt_count"])
            staged_project = attempt_root / "source"
            shutil.copytree(snapshot.project_root, staged_project, symlinks=True)
            staged_snapshot = self.paths.inspect_project(attempt_root, "source")
            if staged_snapshot.sha256 != snapshot.sha256:
                raise MediaWorkerError("Staged project did not match the validated source snapshot.")
            # OpenFilm look/render writes internal caches below <project>/.film.
            # Keep the source files immutable in the container and mount only this
            # per-attempt cache directory writable.
            (staged_project / ".film").mkdir(mode=0o700, exist_ok=False)
            output_path = attempt_root / "master.mp4"
            runner_request = {
                "job_id": job["job_id"],
                "project_root": str(staged_project),
                "entrypoint": "film.html",
                "artifact_root": str(self.config.artifact_root),
                "attempt_root": str(attempt_root),
                "output_path": str(output_path),
                "profile": renderer_profile,
                "max_output_bytes": self.config.max_output_bytes,
            }

            def on_phase(phase: str) -> None:
                nonlocal state
                current = self.jobs.get(job["job_id"])
                if not current or current["state"] == "cancel_requested":
                    raise MediaWorkerError("Cancellation requested before the next render phase.")
                if phase == "inspecting" and state == "claimed":
                    if not self._state_change(job, state, "inspecting"):
                        raise MediaWorkerError("Media job lost its claim before inspection.")
                    state = "inspecting"
                elif phase == "rendering" and state == "inspecting":
                    if not self._state_change(job, state, "rendering"):
                        raise MediaWorkerError("Media job lost its claim before rendering.")
                    state = "rendering"
                elif phase not in {"inspecting", "rendering"}:
                    raise MediaWorkerError("Worker received an unsupported renderer phase.")

            def cancel_check() -> bool:
                current = self.jobs.get(job["job_id"])
                return not current or current["state"] in {"cancel_requested", "cancelled"}

            try:
                runner_result = self.isolation.run_fixed_runner(
                    runner_request,
                    staged_project,
                    attempt_root,
                    limits,
                    self.config.timeout_seconds,
                    on_phase=on_phase,
                    cancel_check=cancel_check,
                )
            finally:
                shutil.rmtree(staged_project)
            current = self.jobs.get(job["job_id"])
            if not current:
                return {"job_id": job["job_id"], "status": "failed", "failure_category": "job_record_missing"}
            if runner_result.get("status") == "cancelled" or current["state"] == "cancel_requested":
                self.jobs.advance(
                    job["job_id"], expected_state="cancel_requested", target_state="cancelled",
                    worker_id=self.config.worker_id, lease_token=job["lease_token"],
                    result={"failure_category": "cancelled"},
                )
                return {"job_id": job["job_id"], "status": "cancelled"}
            if runner_result.get("status") == "qa_blocked":
                self.jobs.advance(
                    job["job_id"], expected_state=state, target_state="qa_blocked",
                    worker_id=self.config.worker_id, lease_token=job["lease_token"],
                    result={
                        "failure_category": runner_result.get("failure_category", "openfilm_look_failed"),
                        "diagnostics": runner_result.get("diagnostics", [])[:20],
                    },
                )
                return {"job_id": job["job_id"], "status": "qa_blocked", "failure_category": runner_result.get("failure_category")}
            if runner_result.get("status") != "rendered":
                return self._finish_failure(
                    job, state,
                    runner_result.get("failure_category", "renderer_failed"),
                    runner_result.get("message", "OpenFilm runner did not return a rendered result."),
                )
            if state != "rendering":
                return self._finish_failure(job, state, "runner_phase_missing", "Renderer completed without an observed rendering phase.")
            if not output_path.is_file() or output_path.is_symlink():
                return self._finish_failure(job, state, "output_missing", "Renderer output was not found in the job attempt directory.")
            if output_path.stat().st_size <= 0 or output_path.stat().st_size > self.config.max_output_bytes:
                return self._finish_failure(job, state, "output_size_invalid", "Renderer output is empty or exceeds the configured size ceiling.")
            transition_result = {
                "openfilm_version": runner_result.get("openfilm_version"),
                "output_size": runner_result.get("output_size"),
                "output_sha256": runner_result.get("output_sha256"),
                "profile": profile,
            }
            if not self._state_change(job, state, "post_render_qa", transition_result):
                return {"job_id": job["job_id"], "status": "failed", "failure_category": "state_transition_conflict"}
            state = "post_render_qa"
            if self.qa is None:
                self.jobs.advance(
                    job["job_id"], expected_state=state, target_state="qa_blocked",
                    worker_id=self.config.worker_id, lease_token=job["lease_token"],
                    result={"failure_category": "post_render_qa_unavailable"},
                )
                return {"job_id": job["job_id"], "status": "qa_blocked", "failure_category": "post_render_qa_unavailable"}
            qa_report = self.qa.run(
                snapshot=snapshot,
                output_path=output_path,
                profile=profile,
                max_output_bytes=self.config.max_output_bytes,
                caption_tracks=request.get("caption_tracks", []),
            )
            if not isinstance(qa_report, dict) or qa_report.get("passed") is not True:
                failure = qa_report.get("failure_category", "technical_qa_failed") if isinstance(qa_report, dict) else "technical_qa_invalid"
                self.jobs.advance(
                    job["job_id"], expected_state=state, target_state="qa_blocked",
                    worker_id=self.config.worker_id, lease_token=job["lease_token"],
                    result={"failure_category": failure, "qa_report": qa_report if isinstance(qa_report, dict) else {}},
                )
                return {"job_id": job["job_id"], "status": "qa_blocked", "failure_category": failure}
            manifest = MediaManifest.build(
                job=job, snapshot=snapshot, output_path=output_path,
                qa_report=qa_report, runner_result=runner_result,
            )
            final_result = {
                **transition_result,
                "qa_status": "passed",
                "qa_report": qa_report,
                "manifest": manifest,
                "artifact_path": str(output_path),
                "artifact_hashes": qa_report.get("artifact_hashes", {}),
            }
            if not self._state_change(job, state, "ready_for_human_review", final_result):
                return {"job_id": job["job_id"], "status": "failed", "failure_category": "finalize_conflict"}
            return {
                "job_id": job["job_id"],
                "status": "ready_for_human_review",
                "artifact_path": str(output_path),
                "artifact_hash": transition_result["output_sha256"],
                "qa_report": qa_report,
                "manifest": manifest,
            }
        except MediaPathError as exc:
            return self._finish_failure(job, state, "project_path_rejected", str(exc))
        except Exception as exc:
            return self._finish_failure(job, state, "worker_execution_failed", type(exc).__name__)
