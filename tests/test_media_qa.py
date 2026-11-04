import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import subprocess

from unexpected_runtime.media.qa import MediaQualityAssurance


class MediaQualityAssuranceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        (self.project / "captions").mkdir(parents=True)
        (self.project / "film.html").write_text("<html></html>", encoding="utf-8")
        (self.project / "captions" / "en.srt").write_text(
            "1\n00:00:00,000 --> 00:00:02,000\nOpening\n\n2\n00:00:02,100 --> 00:00:03,000\nNext\n",
            encoding="utf-8",
        )
        self.output = self.root / "master.mp4"
        self.output.write_bytes(b"synthetic-mp4")
        self.snapshot = SimpleNamespace(
            project_root=self.project,
            sha256="a" * 64,
            files=("film.html", "captions/en.srt"),
        )
        self.qa = MediaQualityAssurance("/usr/bin/ffprobe", "/usr/bin/ffmpeg")
        self.profile = {
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "max_duration_seconds": 30,
            "audio_required": True,
            "audio_coverage_tolerance_seconds": 0.1,
            "audio_loudness_target_lufs": -16,
            "audio_true_peak_ceiling_dbfs": -1,
            "audio_loudness_tolerance_lu": 1,
            "black_frame_min_duration_seconds": 0.1,
            "black_frame_pixel_threshold": 0.1,
            "max_black_duration_seconds": 0.5,
            "freeze_frame_noise": "-50dB",
            "freeze_frame_min_duration_seconds": 0.5,
            "max_freeze_duration_seconds": 0.5,
            "captions_required": True,
        }

    def tearDown(self):
        self.temp.cleanup()

    def _fake_run(self, *, width=1080, audio=True, black_duration=0.1, freeze_duration=0.2):
        streams = [{
            "codec_type": "video", "width": width, "height": 1920,
            "avg_frame_rate": "30/1", "duration": "10",
        }]
        if audio:
            streams.append({"codec_type": "audio", "duration": "10"})
        metadata = {"streams": streams, "format": {"duration": "10", "format_name": "mov,mp4,m4a,3gp,3g2,mj2"}}

        def run(command, **kwargs):
            if command[0].endswith("ffprobe"):
                return subprocess.CompletedProcess(command, 0, json.dumps(metadata), "")
            if "ebur128=framelog=verbose" in command:
                return subprocess.CompletedProcess(command, 0, "", "I: -16.0 LUFS\nPeak: -1.0 dBFS\n")
            if any("blackdetect=" in value for value in command):
                stderr = f"black_duration:{black_duration}\nfreeze_duration: {freeze_duration}\n"
                return subprocess.CompletedProcess(command, 0, "", stderr)
            if "tile=4x4" in " ".join(command):
                Path(command[-1]).write_bytes(b"contact-sheet")
                return subprocess.CompletedProcess(command, 0, "", "")
            raise AssertionError("Unexpected fixed QA command: " + " ".join(command))
        return run

    def test_valid_portrait_video_audio_captions_and_contact_sheet_pass(self):
        with patch("unexpected_runtime.media.qa.subprocess.run", side_effect=self._fake_run()):
            report = self.qa.run(
                snapshot=self.snapshot,
                output_path=self.output,
                profile=self.profile,
                max_output_bytes=1024 * 1024,
                caption_tracks=[{"path": "captions/en.srt", "language": "en"}],
            )
        self.assertTrue(report["passed"], report)
        self.assertTrue(report["checks"]["video_stream_profile"])
        self.assertTrue(report["checks"]["audio_stream_coverage_and_loudness"])
        self.assertTrue(report["checks"]["black_and_freeze_detection"])
        self.assertTrue(report["checks"]["caption_syntax_and_timing"])
        self.assertTrue(report["checks"]["contact_sheet_created"])
        self.assertEqual(len(report["artifact_hashes"]["output_sha256"]), 64)

    def test_wrong_dimensions_missing_audio_and_black_frames_fail_closed(self):
        cases = [
            (self._fake_run(width=720), self.profile, [{"path": "captions/en.srt", "language": "en"}]),
            (self._fake_run(audio=False), self.profile, [{"path": "captions/en.srt", "language": "en"}]),
            (self._fake_run(black_duration=2.0), self.profile, [{"path": "captions/en.srt", "language": "en"}]),
        ]
        for fake, profile, tracks in cases:
            with self.subTest(profile=profile), patch("unexpected_runtime.media.qa.subprocess.run", side_effect=fake):
                report = self.qa.run(
                    snapshot=self.snapshot, output_path=self.output, profile=profile,
                    max_output_bytes=1024 * 1024, caption_tracks=tracks,
                )
                self.assertFalse(report["passed"])
                self.assertEqual(report["failure_category"], "technical_qa_failed")

    def test_missing_audio_targets_and_malformed_captions_fail_closed(self):
        profile = dict(self.profile)
        profile.pop("audio_loudness_target_lufs")
        with patch("unexpected_runtime.media.qa.subprocess.run", side_effect=self._fake_run()):
            missing_target = self.qa.run(
                snapshot=self.snapshot, output_path=self.output, profile=profile,
                max_output_bytes=1024 * 1024, caption_tracks=[],
            )
        self.assertFalse(missing_target["passed"])
        self.assertIn("audio_loudness_target_lufs", missing_target["diagnostics"][0])

        (self.project / "captions" / "en.srt").write_text(
            "1\n00:00:05,000 --> 00:00:02,000\nBad cue\n", encoding="utf-8"
        )
        with patch("unexpected_runtime.media.qa.subprocess.run", side_effect=self._fake_run()):
            malformed = self.qa.run(
                snapshot=self.snapshot, output_path=self.output, profile=self.profile,
                max_output_bytes=1024 * 1024,
                caption_tracks=[{"path": "captions/en.srt", "language": "en"}],
            )
        self.assertFalse(malformed["passed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
