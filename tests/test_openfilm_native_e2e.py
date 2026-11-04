from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(
    os.environ.get("UNEXPECTED_OPENFILM_E2E") == "1",
    "requires the explicitly configured rootless Podman OpenFilm integration host",
)
class NativeOpenFilmEndToEndTests(unittest.TestCase):
    def setUp(self):
        configured_root = os.environ.get("UNEXPECTED_E2E_ROOT")
        self.preserve_root = bool(configured_root)
        self.temp = None
        if configured_root:
            self.root = Path(configured_root).resolve()
            if self.root.exists():
                shutil.rmtree(self.root)
            self.root.mkdir(parents=True)
        else:
            self.temp = tempfile.TemporaryDirectory(prefix="unexpected-openfilm-e2e-")
            self.root = Path(self.temp.name)
        self.projects = self.root / "projects"
        self.project = self.projects / "pilot"
        (self.project / "assets").mkdir(parents=True)
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        self.state = self.root / "state"
        self.state.mkdir()
        self.env = os.environ.copy()
        self.env.update({
            "UNEXPECTED_STORAGE_BACKEND": "sqlite",
            "UNEXPECTED_STATE_DIR": str(self.state),
            "UNEXPECTED_DEFAULT_PROVIDER": "mock",
            "UNEXPECTED_OPENFILM_WORKER_ID": "ci-openfilm-worker",
            "UNEXPECTED_OPENFILM_PROJECT_ROOT": str(self.projects),
            "UNEXPECTED_OPENFILM_ARTIFACT_ROOT": str(self.artifacts),
            "UNEXPECTED_OPENFILM_TIMEOUT_SECONDS": "240",
            "UNEXPECTED_OPENFILM_LEASE_SECONDS": "300",
            "UNEXPECTED_OPENFILM_MAX_PROJECT_BYTES": str(50 * 1024 * 1024),
            "UNEXPECTED_OPENFILM_MAX_ASSET_COUNT": "20",
            "UNEXPECTED_OPENFILM_MAX_FILE_BYTES": str(10 * 1024 * 1024),
            "UNEXPECTED_OPENFILM_MAX_OUTPUT_BYTES": str(500 * 1024 * 1024),
            "UNEXPECTED_OPENFILM_MEMORY_BYTES": str(2 * 1024 * 1024 * 1024),
            "UNEXPECTED_OPENFILM_CPU_LIMIT": "1.5",
            "UNEXPECTED_OPENFILM_PIDS_LIMIT": "64",
            "UNEXPECTED_OPENFILM_TMPFS_BYTES": str(512 * 1024 * 1024),
            "UNEXPECTED_OPENFILM_FFPROBE_PATH": "/usr/bin/ffprobe",
            "UNEXPECTED_OPENFILM_FFMPEG_PATH": "/usr/bin/ffmpeg",
            "UNEXPECTED_OPENFILM_QA_TIMEOUT_SECONDS": "180",
        })
        self.assertTrue(self.env.get("UNEXPECTED_OPENFILM_WORKER_IMAGE"), "CI must supply the immutable worker image ID.")
        self.assertTrue(self.env.get("UNEXPECTED_OPENFILM_PODMAN_PATH"), "CI must supply the Podman executable path.")
        self.env.update({
            "UNEXPECTED_OPENFILM_HOST_MAX_MEMORY_BYTES": str(3 * 1024 * 1024 * 1024),
            "UNEXPECTED_OPENFILM_HOST_MAX_CPU_LIMIT": "2.0",
            "UNEXPECTED_OPENFILM_HOST_MAX_PIDS": "128",
            "UNEXPECTED_OPENFILM_HOST_TMPFS_BYTES": str(1024 * 1024 * 1024),
        })
        self._write_project()

    def tearDown(self):
        if self.temp is not None:
            self.temp.cleanup()

    def _write_project(self):
        (self.project / "film.html").write_text("""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=1080, height=1920">
  <style>html, body { margin: 0; width: 1080px; height: 1920px; overflow: hidden; background: #15283d; }</style>
</head>
<body>
  <section>
    <iframe src="scene.html#t=0,8" style="left: 0; top: 0; width: 1080px; height: 1920px"></iframe>
  </section>
  <section>
    <audio src="assets/bed.wav" volume="0.7"></audio>
  </section>
</body>
</html>
""", encoding="utf-8")
        (self.project / "scene.html").write_text("""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=1080, height=1920">
  <style>
    * { box-sizing: border-box; }
    html, body { margin: 0; width: 1080px; height: 1920px; overflow: hidden; background: #15283d; color: #f3f6ff; font-family: Arial, sans-serif; }
    main { width: 1080px; height: 1920px; padding: 220px 90px; }
    h1 { margin: 0 0 32px; font-size: 82px; line-height: 1.08; }
    p { font-size: 38px; color: #c7d5e8; }
    .track { margin-top: 170px; width: 900px; height: 22px; background: #30465e; border-radius: 12px; overflow: hidden; }
    #progress { height: 22px; width: 0; background: #55d6be; }
    #timestamp { margin-top: 32px; font-size: 28px; color: #9fb5cb; }
  </style>
</head>
<body>
  <main>
    <h1>Native video render</h1>
    <p>One request. One isolated worker. One verified MP4.</p>
    <div class="track"><div id="progress"></div></div>
    <div id="timestamp">0.00s</div>
  </main>
  <script type="module">
    window.film = {
      duration: 8,
      frame(t) {
        const progress = Math.max(0, Math.min(1, t / 8));
        document.querySelector("#progress").style.width = Math.round(progress * 900) + "px";
        document.querySelector("#timestamp").textContent = t.toFixed(2) + "s";
      }
    };
  </script>
</body>
</html>
""", encoding="utf-8")
        (self.project / "captions.srt").write_text(
            "1\n00:00:00,000 --> 00:00:04,000\nNative uneXpected video engine.\n\n"
            "2\n00:00:04,000 --> 00:00:08,000\nRendered locally and checked.\n",
            encoding="utf-8",
        )
        subprocess.run([
            "/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=8:sample_rate=48000",
            "-af", "loudnorm=I=-16:TP=-1.5:LRA=7",
            "-c:a", "pcm_s16le", str(self.project / "assets" / "bed.wav"),
        ], check=True, timeout=30)

    def _cli(self, *arguments, timeout=300):
        result = subprocess.run(
            [sys.executable, "-m", "unexpected_runtime.cli", "media", *arguments],
            cwd=ROOT, env=self.env, text=True, capture_output=True, timeout=timeout,
            check=False,
        )
        self.assertEqual(
            result.returncode, 0,
            f"CLI failed: {' '.join(arguments)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            self.fail(f"CLI did not return JSON: {' '.join(arguments)}\n{result.stdout}\n{result.stderr}")

    def test_video_request_reaches_a_playable_qa_checked_mp4(self):
        self._cli("review", "--reviewer", "ci-owner", "--reason", "Pinned source and worker reviewed in CI")
        self._cli("install", "--reason", "Pinned local worker image built for CI")
        preflight = self._cli("preflight")
        self.assertIs(preflight["worker_readiness"]["available"], True, preflight)

        self._cli("enable", "--reason", "Rootless isolation and cgroup limits passed CI preflight")
        profile = {
            "platform": "youtube_shorts",
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "max_duration_seconds": 12,
            "black_frame_min_duration_seconds": 0.1,
            "black_frame_pixel_threshold": 0.1,
            "max_black_duration_seconds": 0.25,
            "freeze_frame_noise": "-50dB",
            "freeze_frame_min_duration_seconds": 0.5,
            "max_freeze_duration_seconds": 0.5,
            "audio_required": True,
            "audio_coverage_tolerance_seconds": 0.15,
            "audio_loudness_target_lufs": -16,
            "audio_true_peak_ceiling_dbfs": -1,
            "audio_loudness_tolerance_lu": 1.5,
            "captions_required": True,
        }
        request = {
            "task_id": "ci-native-render-task",
            "idempotency_key": "ci-native-render-v1",
            "project_path": "pilot",
            "campaign_id": "UNEXPECTED_NATIVE_E2E",
            "content_id": "CI-NATIVE-RENDER-01",
            "synthetic_data": True,
            "rights_manifest": {
                "sources": [{"kind": "original", "owner": "uneXpected", "notes": "Synthetic CI fixture"}]
            },
            "variants": [profile],
            "caption_tracks": [{"path": "captions.srt", "language": "en"}],
        }
        queued = self._cli("enqueue", "--request-json", json.dumps(request))
        self.assertEqual(queued["state"], "queued")
        rendered = self._cli("worker", "--once", timeout=360)
        self.assertEqual(rendered["status"], "ready_for_human_review", rendered)
        output = Path(rendered["artifact_path"]).resolve()
        self.assertTrue(output.is_file())
        self.assertTrue(output.is_relative_to(self.artifacts))
        self.assertGreater(output.stat().st_size, 10_000)
        self.assertTrue((output.parent / "contact-sheet.jpg").is_file())
        self.assertTrue(rendered["qa_report"]["passed"])
        self.assertEqual(rendered["manifest"]["qa"]["status"], "passed")

        probe = subprocess.run([
            "/usr/bin/ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(output)
        ], check=True, text=True, capture_output=True, timeout=30)
        metadata = json.loads(probe.stdout)
        streams = metadata["streams"]
        video = next(stream for stream in streams if stream["codec_type"] == "video")
        audio = next(stream for stream in streams if stream["codec_type"] == "audio")
        self.assertEqual((video["width"], video["height"]), (1080, 1920))
        self.assertEqual(audio["codec_name"], "aac")
        self.assertGreater(float(metadata["format"]["duration"]), 7.5)

        decode = subprocess.run([
            "/usr/bin/ffmpeg", "-hide_banner", "-v", "error", "-i", str(output), "-f", "null", "-"
        ], check=False, text=True, capture_output=True, timeout=180)
        self.assertEqual(decode.returncode, 0, decode.stderr)

        proof = {
            "status": rendered["status"],
            "job_id": rendered["job_id"],
            "artifact_path": str(output),
            "artifact_size_bytes": output.stat().st_size,
            "artifact_sha256": rendered["artifact_hash"],
            "ffprobe": metadata,
            "decode_exit_code": decode.returncode,
            "qa_report": rendered["qa_report"],
            "manifest": rendered["manifest"],
        }
        (self.artifacts / "e2e-proof.json").write_text(
            json.dumps(proof, indent=2, ensure_ascii=False), encoding="utf-8"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
