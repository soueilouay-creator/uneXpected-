from __future__ import annotations

from pathlib import Path
from typing import Any
import hashlib
import json


class MediaManifest:
    """Builds a portable, non-secret manifest for one human-reviewable render."""

    @staticmethod
    def _canonical_hash(value: Any) -> str:
        encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @classmethod
    def build(cls, *, job: dict[str, Any], snapshot, output_path: str | Path,
              qa_report: dict[str, Any], runner_result: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            request = json.loads(job["request_json"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("Media job request is unavailable for manifest creation.") from None
        if not isinstance(request, dict) or not isinstance(qa_report, dict):
            raise ValueError("Manifest inputs must be JSON objects.")
        output = Path(output_path)
        if output.is_symlink() or not output.is_file():
            raise ValueError("Verified output file is missing.")
        hashes = qa_report.get("artifact_hashes", {})
        if not isinstance(hashes, dict) or not hashes.get("output_sha256"):
            raise ValueError("QA report does not contain an output hash.")
        variants = request.get("variants", [])
        if not isinstance(variants, list):
            variants = []
        captions = request.get("caption_tracks", [])
        if not isinstance(captions, list):
            captions = []
        rights = request.get("rights_manifest", {})
        runner = runner_result if isinstance(runner_result, dict) else {}
        return {
            "schema_version": 1,
            "job_id": job.get("job_id"),
            "task_id": job.get("task_id"),
            "campaign_id": request.get("campaign_id"),
            "content_id": request.get("content_id"),
            "source_code": request.get("source_code"),
            "title": request.get("title"),
            "description": request.get("description"),
            "cta": request.get("cta"),
            "platforms": [item.get("platform") for item in variants if isinstance(item, dict)],
            "render_variants": variants,
            "caption_tracks": [
                {"path": item.get("path"), "language": item.get("language")}
                for item in captions if isinstance(item, dict)
            ],
            "rights_manifest_sha256": cls._canonical_hash(rights),
            "project_files": list(snapshot.files),
            "project_sha256": snapshot.sha256,
            "renderer": {"name": "OpenFilm", "version": runner.get("openfilm_version")},
            "output": {
                "file_name": output.name,
                "size_bytes": output.stat().st_size,
                "sha256": hashes["output_sha256"],
                "contact_sheet_file": qa_report.get("contact_sheet_file"),
                "contact_sheet_sha256": hashes.get("contact_sheet_sha256"),
            },
            "qa": {
                "status": "passed" if qa_report.get("passed") is True else "blocked",
                "checks": qa_report.get("checks", {}),
                "measurements": qa_report.get("measurements", {}),
                "failure_category": qa_report.get("failure_category"),
            },
        }
