from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any
import hashlib
import json
import math
import os
import re
import subprocess


class MediaQAError(RuntimeError):
    """A rendered media artifact could not be technically verified."""


class MediaQualityAssurance:
    """Deterministic FFprobe/FFmpeg checks; never treats missing evidence as PASS."""

    def __init__(self, ffprobe_path: str | Path, ffmpeg_path: str | Path, timeout_seconds: float = 120.0):
        self.ffprobe_path = Path(ffprobe_path)
        self.ffmpeg_path = Path(ffmpeg_path)
        self.timeout_seconds = float(timeout_seconds)
        if not self.ffprobe_path.is_absolute() or not self.ffmpeg_path.is_absolute():
            raise ValueError("FFprobe and FFmpeg paths must be absolute.")
        if not math.isfinite(self.timeout_seconds) or not 1 <= self.timeout_seconds <= 900:
            raise ValueError("QA timeout must be between 1 and 900 seconds.")

    @classmethod
    def from_env(cls) -> "MediaQualityAssurance":
        ffprobe = os.environ.get("UNEXPECTED_OPENFILM_FFPROBE_PATH", "").strip()
        ffmpeg = os.environ.get("UNEXPECTED_OPENFILM_FFMPEG_PATH", "").strip()
        if not ffprobe or not ffmpeg:
            raise MediaQAError("UNEXPECTED_OPENFILM_FFPROBE_PATH and UNEXPECTED_OPENFILM_FFMPEG_PATH are required.")
        timeout = os.environ.get("UNEXPECTED_OPENFILM_QA_TIMEOUT_SECONDS", "120")
        try:
            return cls(ffprobe, ffmpeg, float(timeout))
        except (TypeError, ValueError):
            raise MediaQAError("UNEXPECTED_OPENFILM_QA_TIMEOUT_SECONDS must be a finite number.") from None

    def _run(self, executable: Path, args: list[str]) -> subprocess.CompletedProcess:
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": "/tmp",
            "TMPDIR": "/tmp",
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }
        try:
            result = subprocess.run(
                [str(executable), *args],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MediaQAError(f"Required media QA command failed ({type(exc).__name__}).") from None
        if len(result.stdout.encode("utf-8", errors="replace")) > 128 * 1024:
            raise MediaQAError("Media QA stdout exceeded its fixed diagnostic limit.")
        if len(result.stderr.encode("utf-8", errors="replace")) > 128 * 1024:
            raise MediaQAError("Media QA stderr exceeded its fixed diagnostic limit.")
        if result.returncode != 0:
            raise MediaQAError("Required media QA command returned a non-zero exit status.")
        return result

    @staticmethod
    def _finite_number(value: Any, field: str) -> float:
        if isinstance(value, bool):
            raise MediaQAError(f"QA profile field {field} must be numeric.")
        try:
            result = float(value)
        except (TypeError, ValueError, OverflowError):
            raise MediaQAError(f"QA profile field {field} must be numeric.") from None
        if not math.isfinite(result):
            raise MediaQAError(f"QA profile field {field} must be finite.")
        return result

    @staticmethod
    def _rate(value: Any) -> float:
        if not isinstance(value, str) or "/" not in value:
            raise MediaQAError("Video frame rate is missing or malformed.")
        numerator, denominator = value.split("/", 1)
        try:
            n, d = float(numerator), float(denominator)
        except ValueError:
            raise MediaQAError("Video frame rate is malformed.") from None
        if not math.isfinite(n) or not math.isfinite(d) or d == 0:
            raise MediaQAError("Video frame rate is invalid.")
        return n / d

    @staticmethod
    def _caption_timestamp(value: str) -> float:
        match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})", value.strip())
        if not match:
            raise MediaQAError("Caption timestamp is malformed.")
        hours, minutes, seconds, millis = map(int, match.groups())
        if minutes > 59 or seconds > 59:
            raise MediaQAError("Caption timestamp is outside the valid clock range.")
        return hours * 3600 + minutes * 60 + seconds + millis / 1000

    @classmethod
    def _validate_captions(cls, project_root: Path, caption_tracks: Any, duration: float) -> int:
        if not isinstance(caption_tracks, list):
            raise MediaQAError("caption_tracks must be a JSON array.")
        cue_count = 0
        root = project_root.resolve(strict=True)
        for track in caption_tracks:
            if not isinstance(track, dict) or set(track) - {"path", "language"}:
                raise MediaQAError("Each caption track must contain only path and language.")
            relative = track.get("path")
            language = track.get("language")
            if not isinstance(relative, str) or not relative.strip() or not isinstance(language, str) or not language.strip():
                raise MediaQAError("Each caption track requires a relative path and language.")
            pure = PurePosixPath(relative)
            if pure.is_absolute() or any(part in {"", ".", ".."} or part.startswith(".") for part in pure.parts):
                raise MediaQAError("Caption path must remain inside the project root.")
            path = root.joinpath(*pure.parts)
            if path.is_symlink() or not path.is_file():
                raise MediaQAError("Caption file is missing or is a symlink.")
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root) or resolved.stat().st_size > 1024 * 1024:
                raise MediaQAError("Caption file escaped the project root or exceeded 1 MiB.")
            suffix = resolved.suffix.lower()
            if suffix not in {".srt", ".vtt"}:
                raise MediaQAError("Caption file must be SRT or WebVTT.")
            text = resolved.read_text(encoding="utf-8-sig")
            previous_start = -1.0
            previous_end = -1.0
            for line in text.splitlines():
                if "-->" not in line:
                    continue
                left, right = line.split("-->", 1)
                right_value = right.strip().split()[0] if right.strip() else ""
                start = cls._caption_timestamp(left.strip())
                end = cls._caption_timestamp(right_value)
                if start >= end or start < previous_start or end < previous_end or end > duration + 0.05:
                    raise MediaQAError("Caption cues are non-monotonic or outside the video duration.")
                previous_start, previous_end = start, end
                cue_count += 1
        return cue_count

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def run(
        self,
        *,
        snapshot,
        output_path: str | Path,
        profile: dict[str, Any],
        max_output_bytes: int,
        caption_tracks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        checks: dict[str, bool] = {}
        measurements: dict[str, Any] = {}
        diagnostics: list[str] = []
        output = Path(output_path)
        try:
            if not isinstance(profile, dict):
                raise MediaQAError("Render profile must be a JSON object.")
            required = (
                "width", "height", "fps", "max_duration_seconds",
                "black_frame_min_duration_seconds", "black_frame_pixel_threshold",
                "max_black_duration_seconds", "freeze_frame_noise",
                "freeze_frame_min_duration_seconds", "max_freeze_duration_seconds",
            )
            missing = [name for name in required if name not in profile]
            if missing:
                raise MediaQAError("QA profile is missing required thresholds: " + ", ".join(missing))
            if output.is_symlink() or not output.is_file():
                raise MediaQAError("Rendered MP4 is missing or is a symlink.")
            size = output.stat().st_size
            if size <= 0 or size > int(max_output_bytes):
                raise MediaQAError("Rendered MP4 is empty or exceeds the configured output-byte ceiling.")
            checks["output_exists_and_size"] = True

            probe = self._run(self.ffprobe_path, [
                "-v", "error", "-show_streams", "-show_format", "-of", "json", str(output)
            ])
            try:
                metadata = json.loads(probe.stdout)
            except json.JSONDecodeError:
                raise MediaQAError("FFprobe returned invalid JSON.") from None
            streams = metadata.get("streams")
            if not isinstance(streams, list):
                raise MediaQAError("FFprobe did not return a stream list.")
            video = next((item for item in streams if item.get("codec_type") == "video"), None)
            audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
            if not isinstance(video, dict):
                raise MediaQAError("Rendered MP4 has no video stream.")
            width, height = int(video.get("width", 0)), int(video.get("height", 0))
            if width != int(profile["width"]) or height != int(profile["height"]):
                raise MediaQAError("Rendered MP4 dimensions do not match the requested platform variant.")
            fps = self._rate(video.get("avg_frame_rate") or video.get("r_frame_rate"))
            expected_fps = self._finite_number(profile["fps"], "fps")
            if abs(fps - expected_fps) > 0.05:
                raise MediaQAError("Rendered MP4 frame rate does not match the requested profile.")
            format_data = metadata.get("format") if isinstance(metadata.get("format"), dict) else {}
            duration_value = format_data.get("duration") or video.get("duration")
            duration = self._finite_number(duration_value, "measured_duration")
            max_duration = self._finite_number(profile["max_duration_seconds"], "max_duration_seconds")
            if duration <= 0 or duration > max_duration:
                raise MediaQAError("Rendered MP4 duration is empty or exceeds the declared ceiling.")
            checks["video_stream_profile"] = True
            measurements.update({"width": width, "height": height, "fps": fps, "duration_seconds": duration, "size_bytes": size})

            audio_required = profile.get("audio_required", False)
            if not isinstance(audio_required, bool):
                raise MediaQAError("audio_required must be a boolean.")
            if audio_required:
                if not isinstance(audio, dict):
                    raise MediaQAError("Required audio stream is missing.")
                audio_duration = self._finite_number(audio.get("duration") or format_data.get("duration"), "audio_duration")
                coverage_tolerance = self._finite_number(profile.get("audio_coverage_tolerance_seconds"), "audio_coverage_tolerance_seconds")
                if audio_duration + coverage_tolerance < duration:
                    raise MediaQAError("Audio does not cover the required video duration.")
                target_lufs = self._finite_number(profile.get("audio_loudness_target_lufs"), "audio_loudness_target_lufs")
                peak_ceiling = self._finite_number(profile.get("audio_true_peak_ceiling_dbfs"), "audio_true_peak_ceiling_dbfs")
                loudness_tolerance = self._finite_number(profile.get("audio_loudness_tolerance_lu"), "audio_loudness_tolerance_lu")
                loudness = self._run(self.ffmpeg_path, [
                    "-hide_banner", "-nostats", "-i", str(output),
                    "-vn", "-af", "ebur128=framelog=verbose", "-f", "null", "-"
                ])
                i_values = re.findall(r"I:\s*(-?\d+(?:\.\d+)?)\s*LUFS", loudness.stderr)
                peak_values = re.findall(r"Peak:\s*(-?\d+(?:\.\d+)?)\s*dBFS", loudness.stderr)
                if not i_values or not peak_values:
                    raise MediaQAError("FFmpeg did not report integrated loudness and true peak.")
                integrated = float(i_values[-1])
                true_peak = float(peak_values[-1])
                if abs(integrated - target_lufs) > loudness_tolerance or true_peak > peak_ceiling:
                    raise MediaQAError("Audio loudness or true peak is outside the declared QA profile.")
                checks["audio_stream_coverage_and_loudness"] = True
                measurements.update({"audio_duration_seconds": audio_duration, "integrated_loudness_lufs": integrated, "true_peak_dbfs": true_peak})
            else:
                checks["audio_required"] = True

            black_min = self._finite_number(profile["black_frame_min_duration_seconds"], "black_frame_min_duration_seconds")
            black_pixel = self._finite_number(profile["black_frame_pixel_threshold"], "black_frame_pixel_threshold")
            black_max = self._finite_number(profile["max_black_duration_seconds"], "max_black_duration_seconds")
            freeze_noise = str(profile["freeze_frame_noise"])
            if not re.fullmatch(r"-?\d+(?:\.\d+)?dB", freeze_noise):
                raise MediaQAError("freeze_frame_noise must be a dB threshold such as -50dB.")
            freeze_min = self._finite_number(profile["freeze_frame_min_duration_seconds"], "freeze_frame_min_duration_seconds")
            freeze_max = self._finite_number(profile["max_freeze_duration_seconds"], "max_freeze_duration_seconds")
            filters = f"blackdetect=d={black_min}:pix_th={black_pixel},freezedetect=n={freeze_noise}:d={freeze_min}"
            detection = self._run(self.ffmpeg_path, [
                "-hide_banner", "-nostats", "-i", str(output),
                "-vf", filters, "-an", "-f", "null", "-"
            ])
            black_durations = [float(x) for x in re.findall(r"black_duration:([0-9]+(?:\.\d+)?)", detection.stderr)]
            freeze_durations = [float(x) for x in re.findall(r"freeze_duration:\s*([0-9]+(?:\.\d+)?)", detection.stderr)]
            black_total = sum(black_durations)
            freeze_total = sum(freeze_durations)
            if black_total > black_max or freeze_total > freeze_max:
                raise MediaQAError("Black-frame or freeze-frame duration exceeds the declared QA profile.")
            checks["black_and_freeze_detection"] = True
            measurements.update({"black_duration_seconds": black_total, "freeze_duration_seconds": freeze_total})

            tracks = caption_tracks if caption_tracks is not None else []
            cue_count = self._validate_captions(snapshot.project_root, tracks, duration)
            if profile.get("captions_required", False) and cue_count == 0:
                raise MediaQAError("Captions are required but no valid caption cues were found.")
            checks["caption_syntax_and_timing"] = True
            measurements["caption_cue_count"] = cue_count

            contact_sheet = output.parent / "contact-sheet.jpg"
            if contact_sheet.exists() or contact_sheet.is_symlink():
                raise MediaQAError("Contact-sheet destination already exists; outputs are never overwritten.")
            self._run(self.ffmpeg_path, [
                "-hide_banner", "-loglevel", "error", "-i", str(output),
                "-vf", "fps=1/5,scale=320:-1,tile=4x4",
                "-frames:v", "1", "-q:v", "3", str(contact_sheet)
            ])
            if not contact_sheet.is_file() or contact_sheet.stat().st_size <= 0:
                raise MediaQAError("FFmpeg did not produce a human-review contact sheet.")
            checks["contact_sheet_created"] = True
            hashes = {
                "project_sha256": snapshot.sha256,
                "output_sha256": self._sha256(output),
                "contact_sheet_sha256": self._sha256(contact_sheet),
            }
            return {
                "passed": True,
                "checks": checks,
                "measurements": measurements,
                "artifact_hashes": hashes,
                "contact_sheet_file": contact_sheet.name,
                "failure_category": None,
                "diagnostics": [],
            }
        except (MediaQAError, OSError, ValueError, TypeError, KeyError) as exc:
            diagnostics.append(str(exc)[:300])
            return {
                "passed": False,
                "checks": checks,
                "measurements": measurements,
                "artifact_hashes": {},
                "failure_category": "technical_qa_failed",
                "diagnostics": diagnostics[:20],
            }
