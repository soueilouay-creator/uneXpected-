from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import hashlib
import os
import re
import stat


class MediaPathError(ValueError):
    """A media project or artifact path violates the job-root policy."""


ALLOWED_ASSET_SUFFIXES = frozenset({
    ".html", ".htm", ".css", ".js", ".mjs", ".json", ".svg", ".png",
    ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".mov", ".m4v", ".webm",
    ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".woff", ".woff2",
    ".ttf", ".otf", ".glb", ".gltf", ".txt", ".vtt", ".srt",
})
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class ProjectSnapshot:
    project_root: Path
    entrypoint: Path
    asset_count: int
    total_bytes: int
    sha256: str
    files: tuple[str, ...]


class MediaPathPolicy:
    """Checks every project component without following links or special files."""

    def __init__(
        self,
        *,
        artifact_root: str | Path | None = None,
        max_project_bytes: int = 256 * 1024 * 1024,
        max_asset_count: int = 500,
        max_file_bytes: int = 128 * 1024 * 1024,
    ):
        for name, value in (
            ("max_project_bytes", max_project_bytes),
            ("max_asset_count", max_asset_count),
            ("max_file_bytes", max_file_bytes),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer.")
        if max_file_bytes > max_project_bytes:
            raise ValueError("max_file_bytes cannot exceed max_project_bytes.")
        self.artifact_root = Path(artifact_root) if artifact_root is not None else None
        self.max_project_bytes = max_project_bytes
        self.max_asset_count = max_asset_count
        self.max_file_bytes = max_file_bytes

    @staticmethod
    def _safe_relative(value: str, name: str) -> PurePosixPath:
        if not isinstance(value, str) or not value.strip() or "\x00" in value or "\\" in value:
            raise MediaPathError(f"{name} must be a non-empty POSIX relative path.")
        candidate = PurePosixPath(value)
        if not candidate.parts or candidate.is_absolute() or any(part in {"", ".", ".."} or part.startswith(".") for part in candidate.parts):
            raise MediaPathError(f"{name} must not contain absolute, traversal or hidden components.")
        return candidate

    @staticmethod
    def _real_directory(value: str | Path, name: str) -> Path:
        path = Path(value)
        try:
            details = path.lstat()
        except OSError:
            raise MediaPathError(f"{name} does not exist or cannot be inspected.") from None
        if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
            raise MediaPathError(f"{name} must be a real directory, not a symlink or special file.")
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            raise MediaPathError(f"{name} could not be resolved safely.") from None
        if resolved != path.absolute():
            # Reject parent-component symlinks as well as a symlink at the final component.
            raise MediaPathError(f"{name} contains a symlinked path component.")
        return resolved

    def inspect_project(self, configured_root: str | Path, project_relative_path: str) -> ProjectSnapshot:
        root = self._real_directory(configured_root, "configured project root")
        relative = self._safe_relative(project_relative_path, "project path")
        project = root.joinpath(*relative.parts)
        try:
            details = project.lstat()
        except OSError:
            raise MediaPathError("Project directory does not exist.") from None
        if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
            raise MediaPathError("Project path must resolve to a real directory.")
        try:
            project = project.resolve(strict=True)
        except OSError:
            raise MediaPathError("Project directory could not be resolved.") from None
        if not project.is_relative_to(root):
            raise MediaPathError("Project directory escaped the configured root.")

        files: list[tuple[str, Path, int]] = []
        total = 0
        for current, dirnames, filenames in os.walk(project, topdown=True, followlinks=False):
            current_path = Path(current)
            for dirname in list(dirnames):
                if dirname.startswith("."):
                    raise MediaPathError("Hidden runtime directories are not accepted in a project.")
                child = current_path / dirname
                try:
                    child_stat = child.lstat()
                except OSError:
                    raise MediaPathError("A project directory disappeared during inspection.") from None
                if stat.S_ISLNK(child_stat.st_mode) or not stat.S_ISDIR(child_stat.st_mode):
                    raise MediaPathError("Project directories must not contain symlinks or special files.")
                if not child.resolve(strict=True).is_relative_to(project):
                    raise MediaPathError("A project directory escapes the project root.")
            dirnames.sort()
            for filename in sorted(filenames):
                if filename.startswith("."):
                    raise MediaPathError("Hidden runtime files are not accepted in a project.")
                file_path = current_path / filename
                try:
                    file_stat = file_path.lstat()
                except OSError:
                    raise MediaPathError("A project asset disappeared during inspection.") from None
                if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
                    raise MediaPathError("Project assets must be regular files, not links or device files.")
                suffix = file_path.suffix.lower()
                if suffix not in ALLOWED_ASSET_SUFFIXES:
                    raise MediaPathError(f"Unsupported project asset type: {suffix or '<no extension>'}.")
                if file_stat.st_size > self.max_file_bytes:
                    raise MediaPathError("A project asset exceeds the per-file byte limit.")
                total += file_stat.st_size
                if total > self.max_project_bytes:
                    raise MediaPathError("Project exceeds the configured total byte limit.")
                files.append((file_path.relative_to(project).as_posix(), file_path, file_stat.st_size))
                if len(files) > self.max_asset_count:
                    raise MediaPathError("Project exceeds the configured asset-count limit.")
        if not files:
            raise MediaPathError("Project contains no regular media files.")
        entrypoint = project / "film.html"
        if not any(relative_name == "film.html" for relative_name, _, _ in files):
            raise MediaPathError("Project must contain film.html at its root.")
        digest = hashlib.sha256()
        for relative_name, file_path, expected_size in files:
            # Re-check the file identity immediately before reading it.
            try:
                before = file_path.lstat()
                if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
                    raise MediaPathError("A project file changed type during inspection.")
                if before.st_size != expected_size:
                    raise MediaPathError("A project file changed size during inspection.")
                digest.update(relative_name.encode("utf-8") + b"\0")
                with file_path.open("rb") as stream:
                    remaining = expected_size
                    while remaining:
                        chunk = stream.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise MediaPathError("A project file changed while being hashed.")
                        digest.update(chunk)
                        remaining -= len(chunk)
                    if stream.read(1):
                        raise MediaPathError("A project file grew while being hashed.")
            except OSError:
                raise MediaPathError("A project file could not be safely read.") from None
        return ProjectSnapshot(
            project_root=project,
            entrypoint=entrypoint,
            asset_count=len(files),
            total_bytes=total,
            sha256=digest.hexdigest(),
            files=tuple(name for name, _, _ in files),
        )

    def prepare_attempt(self, job_id: str, attempt_number: int) -> Path:
        if not isinstance(job_id, str) or not SAFE_ID.fullmatch(job_id):
            raise MediaPathError("job_id contains unsupported characters.")
        if isinstance(attempt_number, bool) or not isinstance(attempt_number, int) or attempt_number < 1:
            raise MediaPathError("attempt_number must be a positive integer.")
        if self.artifact_root is None:
            raise MediaPathError("A configured artifact root is required.")
        root = self._real_directory(self.artifact_root, "configured artifact root")
        job_dir = root / job_id
        try:
            job_dir.mkdir(mode=0o700, exist_ok=True)
            job_stat = job_dir.lstat()
        except OSError:
            raise MediaPathError("Could not create the job artifact directory.") from None
        if stat.S_ISLNK(job_stat.st_mode) or not stat.S_ISDIR(job_stat.st_mode):
            raise MediaPathError("Job artifact directory must be a real directory.")
        if not job_dir.resolve(strict=True).is_relative_to(root):
            raise MediaPathError("Job artifact directory escaped the artifact root.")
        attempt = job_dir / f"attempt-{attempt_number}"
        try:
            attempt.mkdir(mode=0o700, exist_ok=False)
        except FileExistsError:
            raise MediaPathError("Attempt directory already exists; artifacts are never overwritten.") from None
        except OSError:
            raise MediaPathError("Could not create a unique attempt directory.") from None
        return attempt.resolve(strict=True)
