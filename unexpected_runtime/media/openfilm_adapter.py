from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any
import json

from ..capabilities import CapabilityRecord
from ..mcp_gateway import MCPToolCallContext, MCPToolDescriptor
from .jobs import MediaJobService


class OpenFilmAdapterError(ValueError):
    """A malformed or disallowed OpenFilm job request."""


ROLE_IDS = ("orchestrator", "creative-director", "media-producer", "voice-agent")
SOURCE_URL = "https://github.com/openfilm/openfilm"
SOURCE_PUBLISHER = "OpenFilm contributors"
OPENFILM_VERSION = "0.2.7"
TOOL_CREATE = "openfilm.job.create"
TOOL_STATUS = "openfilm.job.status"
TOOL_CANCEL = "openfilm.job.cancel"


class OpenFilmAdapter:
    """Governed enqueue/status/cancel adapter; it never performs a render."""

    def __init__(self, jobs: MediaJobService, capability: CapabilityRecord, worker_ready=None):
        self.jobs = jobs
        self.capability = capability
        self.worker_ready = worker_ready

    def describe(self) -> tuple[MCPToolDescriptor, ...]:
        common = {
            "capability_id": self.capability.capability_id,
            "source_url": self.capability.source_url,
            "source_publisher": self.capability.source_publisher,
            "version": self.capability.version,
            "content_sha256": self.capability.content_sha256,
            "allowed_agent_ids": ROLE_IDS,
            "required_permissions": ("media.local_render",),
            "timeout_seconds": 10.0,
            "data_access": self.capability.data_access,
            "max_argument_bytes": 32 * 1024,
            "max_result_bytes": 16 * 1024,
        }
        return (
            MCPToolDescriptor(
                tool_id=TOOL_CREATE,
                name="Queue OpenFilm render",
                description="Validate and enqueue one local OpenFilm render request.",
                **common,
            ),
            MCPToolDescriptor(
                tool_id=TOOL_STATUS,
                name="Inspect OpenFilm render",
                description="Return bounded state, QA summary and artifact hashes for one job.",
                **common,
            ),
            MCPToolDescriptor(
                tool_id=TOOL_CANCEL,
                name="Cancel OpenFilm render",
                description="Request cancellation of a queued or running media job.",
                **common,
            ),
        )

    @staticmethod
    def _relative_project_path(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise OpenFilmAdapterError("project_path must be a non-empty relative path.")
        if "\\" in value or "\x00" in value:
            raise OpenFilmAdapterError("project_path contains an unsupported path separator or NUL.")
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in {".", ".."} for part in path.parts):
            raise OpenFilmAdapterError("project_path must remain inside the configured project root.")
        if any(part.startswith(".") for part in path.parts):
            raise OpenFilmAdapterError("Hidden project/runtime paths are not accepted.")
        if len(value.encode("utf-8")) > 1024:
            raise OpenFilmAdapterError("project_path exceeds the path-length limit.")
        return path.as_posix()

    @classmethod
    def _create_arguments(cls, arguments: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "task_id", "idempotency_key", "project_path", "campaign_id",
            "content_id", "source_code", "variants", "rights_manifest",
            "synthetic_data", "title", "description", "cta", "caption_tracks",
        }
        if set(arguments) - allowed:
            raise OpenFilmAdapterError("Unsupported media-job fields were supplied.")
        for field in ("task_id", "idempotency_key", "campaign_id", "content_id"):
            if not isinstance(arguments.get(field), str) or not arguments[field].strip():
                raise OpenFilmAdapterError(f"{field} must be a non-empty string.")
        if not isinstance(arguments.get("synthetic_data"), bool):
            raise OpenFilmAdapterError("synthetic_data must be a boolean.")
        if not isinstance(arguments.get("rights_manifest"), (dict, list)):
            raise OpenFilmAdapterError("rights_manifest must be a JSON object or array.")
        variants = arguments.get("variants")
        if not isinstance(variants, list) or len(variants) != 1:
            raise OpenFilmAdapterError("Each media job must contain exactly one render variant.")
        for variant in variants:
            if not isinstance(variant, dict):
                raise OpenFilmAdapterError("Each render variant must be a JSON object.")
            if variant.get("platform") not in {"youtube_shorts", "tiktok", "youtube_long"}:
                raise OpenFilmAdapterError("Unsupported media platform variant.")
            width, height = variant.get("width"), variant.get("height")
            if any(isinstance(value, bool) or not isinstance(value, int) for value in (width, height)):
                raise OpenFilmAdapterError("Variant width and height must be integers.")
            expected = (1920, 1080) if variant["platform"] == "youtube_long" else (1080, 1920)
            if (width, height) != expected:
                raise OpenFilmAdapterError("Variant dimensions do not match the declared profile.")
        request = {
            key: value for key, value in arguments.items()
            if key not in {"task_id", "idempotency_key"}
        }
        request["project_path"] = cls._relative_project_path(request.get("project_path"))
        return {
            "task_id": arguments["task_id"],
            "idempotency_key": arguments["idempotency_key"],
            "request": request,
        }

    @staticmethod
    def _bounded_status(job: dict[str, Any]) -> dict[str, Any]:
        result = {}
        if job.get("result_json"):
            try:
                parsed = json.loads(job["result_json"])
                if isinstance(parsed, dict):
                    result = {
                        "qa_status": parsed.get("qa_status"),
                        "failure_category": parsed.get("failure_category"),
                        "artifact_hashes": parsed.get("artifact_hashes", {}),
                    }
            except (TypeError, ValueError):
                result = {"failure_category": "stored_result_invalid"}
        return {
            "job_id": job["job_id"],
            "state": job["state"],
            "attempt_count": job["attempt_count"],
            "cancel_requested": job["cancel_requested"],
            "request_sha256": job["request_sha256"],
            **({"result": result} if result else {}),
        }

    def call(
        self, tool_id: str, arguments: dict[str, Any], context: MCPToolCallContext
    ) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise OpenFilmAdapterError("Tool arguments must be a JSON object.")
        if tool_id == TOOL_CREATE:
            request = self._create_arguments(arguments)
            job = self.jobs.create(
                task_id=request["task_id"],
                idempotency_key=request["idempotency_key"],
                request=request["request"],
            )
            return {
                "job_id": job["job_id"],
                "state": job["state"],
                "replayed": bool(job.get("replayed")),
            }
        if tool_id == TOOL_STATUS:
            job_id = arguments.get("job_id")
            if set(arguments) != {"job_id"} or not isinstance(job_id, str) or not job_id.strip():
                raise OpenFilmAdapterError("status requires only a non-empty job_id.")
            job = self.jobs.get(job_id)
            if job is None:
                raise OpenFilmAdapterError("Unknown media job.")
            return self._bounded_status(job)
        if tool_id == TOOL_CANCEL:
            job_id = arguments.get("job_id")
            if set(arguments) != {"job_id"} or not isinstance(job_id, str) or not job_id.strip():
                raise OpenFilmAdapterError("cancel requires only a non-empty job_id.")
            state = self.jobs.cancel(job_id)
            if state is None:
                raise OpenFilmAdapterError("Unknown media job.")
            return {"job_id": job_id, "state": state}
        raise OpenFilmAdapterError("Unknown OpenFilm tool ID.")
