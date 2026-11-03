import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from unexpected_runtime.media.manifest import MediaManifest


class MediaManifestTests(unittest.TestCase):
    def test_manifest_contains_provenance_hashes_without_host_paths_or_secrets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "master.mp4"
            output.write_bytes(b"verified-video")
            job = {
                "job_id": "media-job-1",
                "task_id": "task-1",
                "created_at": 1762100000,
                "request_json": json.dumps({
                    "campaign_id": "MAINTENANCE_TRACKER_GROWTH",
                    "content_id": "YT-TRACKER-03",
                    "source_code": "YT-TRACKER-03",
                    "title": "Spare parts risk",
                    "description": "A factual explainer",
                    "cta": "Download the tracker",
                    "project_path": "pilot",
                    "variants": [{"platform": "youtube_shorts", "width": 1080, "height": 1920}],
                    "caption_tracks": [{"path": "captions/en.srt", "language": "en"}],
                    "rights_manifest": {"source": "original", "private_token": "DO_NOT_LEAK"},
                }),
            }
            snapshot = SimpleNamespace(
                sha256="a" * 64,
                files=("film.html", "captions/en.srt"),
            )
            qa = {
                "passed": True,
                "checks": {"video_stream_profile": True},
                "measurements": {"duration_seconds": 12.0},
                "artifact_hashes": {
                    "output_sha256": "b" * 64,
                    "contact_sheet_sha256": "c" * 64,
                },
                "contact_sheet_file": "contact-sheet.jpg",
            }
            manifest = MediaManifest.build(
                job=job, snapshot=snapshot, output_path=output, qa_report=qa,
                runner_result={"openfilm_version": "0.2.7"},
            )
            serialized = json.dumps(manifest)
            self.assertEqual(manifest["campaign_id"], "MAINTENANCE_TRACKER_GROWTH")
            self.assertEqual(manifest["renderer"]["version"], "0.2.7")
            self.assertEqual(manifest["output"]["sha256"], "b" * 64)
            self.assertEqual(manifest["qa"]["status"], "passed")
            self.assertIn("film.html", manifest["project_files"])
            self.assertNotIn(str(root), serialized)
            self.assertNotIn("DO_NOT_LEAK", serialized)
            self.assertNotIn("private_token", serialized)
            self.assertNotIn("artifact_path", serialized)


if __name__ == "__main__":
    unittest.main(verbosity=2)
