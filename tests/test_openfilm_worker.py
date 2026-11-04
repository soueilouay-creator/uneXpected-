import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from unexpected_runtime.media.jobs import MediaJobService
from unexpected_runtime.media.worker import MediaWorker, MediaWorkerConfig
from unexpected_runtime.storage import StateStore


class FakeIsolation:
    def __init__(self, available=True, cancel_hook=None, result_status="rendered"):
        self.available = available
        self.cancel_hook = cancel_hook
        self.result_status = result_status
        self.calls = 0
        self.requests = []
        self.project_snapshots = []

    def self_test(self):
        return {
            "available": self.available,
            "reason": None if self.available else "fake host unavailable",
        }

    def run_fixed_runner(self, request, project_root, attempt_root, limits, timeout_seconds,
                         *, on_phase, cancel_check):
        self.calls += 1
        self.requests.append(request)
        source = Path(project_root)
        self.project_snapshots.append({
            "path": source,
            "cache_exists": (source / ".film").is_dir(),
            "film_html": (source / "film.html").read_text(encoding="utf-8"),
        })
        on_phase("inspecting")
        if self.cancel_hook:
            self.cancel_hook()
        if cancel_check():
            return {"status": "cancelled", "failure_category": "cancelled"}
        on_phase("rendering")
        if self.result_status == "rendered":
            output = Path(request["output_path"])
            output.write_bytes(b"synthetic-mp4-output")
            return {
                "status": "rendered",
                "output_path": str(output),
                "output_size": output.stat().st_size,
                "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                "profile": request["profile"],
            }
        return {
            "status": self.result_status,
            "failure_category": "fake_renderer_failure",
            "diagnostics": ["synthetic failure"],
        }


class FakeQA:
    def __init__(self, passed=True):
        self.passed = passed
        self.calls = 0
        self.last_profile = None

    def run(self, *, snapshot, output_path, profile, max_output_bytes, caption_tracks=None):
        self.calls += 1
        self.last_profile = profile
        output = Path(output_path)
        return {
            "passed": self.passed,
            "checks": {"output_exists": output.is_file(), "synthetic_fixture": True},
            "artifact_hashes": {
                "project_sha256": snapshot.sha256,
                "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            },
            "failure_category": None if self.passed else "qa_fixture_failure",
        }


class OpenFilmWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.projects = self.root / "projects"
        self.project = self.projects / "pilot"
        self.project.mkdir(parents=True)
        (self.project / "film.html").write_text("<html><body>synthetic</body></html>", encoding="utf-8")
        self.artifacts = self.root / "artifacts"
        self.artifacts.mkdir()
        self.store = StateStore(self.root / "state.sqlite3")
        self.jobs = MediaJobService(self.store)
        self.config = MediaWorkerConfig(
            worker_id="test-worker",
            project_root=self.projects,
            artifact_root=self.artifacts,
            timeout_seconds=30,
            lease_seconds=90,
            max_project_bytes=1024 * 1024,
            max_asset_count=10,
            max_file_bytes=1024 * 1024,
            max_output_bytes=2 * 1024 * 1024,
            memory_bytes=512 * 1024 * 1024,
            cpu_limit=1.0,
            pids_limit=64,
            tmpfs_bytes=256 * 1024 * 1024,
        )

    def tearDown(self):
        self.temp.cleanup()

    def create_job(self, task_id, key, project_path="pilot"):
        return self.jobs.create(
            task_id=task_id,
            idempotency_key=key,
            request={
                "project_path": project_path,
                "campaign_id": "MAINTENANCE_TRACKER_GROWTH",
                "content_id": "YT-TRACKER-TEST-01",
                "synthetic_data": True,
                "rights_manifest": {"sources": [{"kind": "original"}]},
                "variants": [{
                    "platform": "youtube_shorts",
                    "width": 1080,
                    "height": 1920,
                    "fps": 30,
                    "audio_required": True,
                }],
            },
        )

    def test_unavailable_isolation_does_not_claim_a_job(self):
        created = self.create_job("task-a", "key-a")
        isolation = FakeIsolation(available=False)
        worker = MediaWorker(self.jobs, isolation, self.config, qa=FakeQA())
        result = worker.run_once()
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(self.jobs.get(created["job_id"])["state"], "queued")
        self.assertEqual(isolation.calls, 0)

    def test_one_job_reaches_human_review_and_worker_exits(self):
        first = self.create_job("task-a", "key-a")
        second = self.create_job("task-b", "key-b")
        isolation, qa = FakeIsolation(), FakeQA()
        worker = MediaWorker(self.jobs, isolation, self.config, qa=qa)
        result = worker.run_once()
        self.assertEqual(result["status"], "ready_for_human_review")
        self.assertEqual(self.jobs.get(first["job_id"])["state"], "ready_for_human_review")
        self.assertEqual(self.jobs.get(second["job_id"])["state"], "queued")
        self.assertEqual(isolation.calls, 1)
        self.assertEqual(qa.calls, 1)
        self.assertTrue(Path(result["artifact_path"]).is_file())
        self.assertEqual(result["manifest"]["qa"]["status"], "passed")
        self.assertEqual(result["manifest"]["campaign_id"], "MAINTENANCE_TRACKER_GROWTH")
        self.assertNotEqual(result["status"], "published")

    def test_runner_receives_only_renderer_profile_while_qa_keeps_full_thresholds(self):
        profile = {
            "platform": "youtube_shorts", "width": 1080, "height": 1920,
            "fps": 30, "audio_required": True,
            "max_duration_seconds": 180,
            "black_frame_min_duration_seconds": 0.1,
            "black_frame_pixel_threshold": 0.1,
            "max_black_duration_seconds": 0.5,
            "freeze_frame_noise": "-50dB",
            "freeze_frame_min_duration_seconds": 0.5,
            "max_freeze_duration_seconds": 0.5,
            "audio_coverage_tolerance_seconds": 0.1,
            "audio_loudness_target_lufs": -16,
            "audio_true_peak_ceiling_dbfs": -1,
            "audio_loudness_tolerance_lu": 1,
            "captions_required": True,
        }
        created = self.jobs.create(
            task_id="task-profile", idempotency_key="profile-filter",
            request={
                "project_path": "pilot", "campaign_id": "MAINTENANCE_TRACKER_GROWTH",
                "content_id": "YT-TRACKER-PROFILE", "synthetic_data": True,
                "rights_manifest": {"sources": [{"kind": "original"}]},
                "variants": [profile], "caption_tracks": [],
            },
        )
        isolation, qa = FakeIsolation(), FakeQA()
        worker = MediaWorker(self.jobs, isolation, self.config, qa=qa)
        result = worker.run_once()
        self.assertEqual(result["status"], "ready_for_human_review")
        self.assertEqual(isolation.requests[0]["profile"], {
            "platform": "youtube_shorts", "width": 1080, "height": 1920,
            "fps": 30, "audio_required": True,
        })
        self.assertEqual(qa.last_profile, profile)
        self.assertEqual(self.jobs.get(created["job_id"])["state"], "ready_for_human_review")

    def test_runner_receives_only_renderer_profile_while_qa_keeps_full_thresholds(self):
        profile = {
            "platform": "youtube_shorts", "width": 1080, "height": 1920,
            "fps": 30, "audio_required": True,
            "max_duration_seconds": 180,
            "black_frame_min_duration_seconds": 0.1,
            "black_frame_pixel_threshold": 0.1,
            "max_black_duration_seconds": 0.5,
            "freeze_frame_noise": "-50dB",
            "freeze_frame_min_duration_seconds": 0.5,
            "max_freeze_duration_seconds": 0.5,
            "audio_coverage_tolerance_seconds": 0.1,
            "audio_loudness_target_lufs": -16,
            "audio_true_peak_ceiling_dbfs": -1,
            "audio_loudness_tolerance_lu": 1,
            "captions_required": True,
        }
        created = self.jobs.create(
            task_id="task-profile", idempotency_key="profile-filter",
            request={
                "project_path": "pilot", "campaign_id": "MAINTENANCE_TRACKER_GROWTH",
                "content_id": "YT-TRACKER-PROFILE", "synthetic_data": True,
                "rights_manifest": {"sources": [{"kind": "original"}]},
                "variants": [profile], "caption_tracks": [],
            },
        )
        isolation, qa = FakeIsolation(), FakeQA()
        worker = MediaWorker(self.jobs, isolation, self.config, qa=qa)
        result = worker.run_once()
        self.assertEqual(result["status"], "ready_for_human_review")
        self.assertEqual(isolation.requests[0]["profile"], {
            "platform": "youtube_shorts", "width": 1080, "height": 1920,
            "fps": 30, "audio_required": True,
        })
        self.assertEqual(qa.last_profile, profile)
        self.assertEqual(self.jobs.get(created["job_id"])["state"], "ready_for_human_review")

    def test_automated_qa_failure_blocks_the_artifact(self):
        created = self.create_job("task-a", "key-a")
        worker = MediaWorker(self.jobs, FakeIsolation(), self.config, qa=FakeQA(passed=False))
        result = worker.run_once()
        self.assertEqual(result["status"], "qa_blocked")
        self.assertEqual(self.jobs.get(created["job_id"])["state"], "qa_blocked")

    def test_cancel_requested_by_operator_is_confirmed_after_runner_stops(self):
        created = self.create_job("task-a", "key-a")
        isolation = FakeIsolation(cancel_hook=lambda: self.jobs.cancel(created["job_id"]))
        worker = MediaWorker(self.jobs, isolation, self.config, qa=FakeQA())
        result = worker.run_once()
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(self.jobs.get(created["job_id"])["state"], "cancelled")

    def test_invalid_project_path_fails_job_before_container_execution(self):
        created = self.create_job("task-a", "key-a", project_path="../outside")
        isolation = FakeIsolation()
        worker = MediaWorker(self.jobs, isolation, self.config, qa=FakeQA())
        result = worker.run_once()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.jobs.get(created["job_id"])["state"], "failed")
        self.assertEqual(isolation.calls, 0)

    def test_render_failure_is_recorded_and_only_one_job_is_claimed(self):
        first = self.create_job("task-a", "key-a")
        second = self.create_job("task-b", "key-b")
        worker = MediaWorker(self.jobs, FakeIsolation(result_status="failed"), self.config, qa=FakeQA())
        result = worker.run_once()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(self.jobs.get(first["job_id"])["state"], "failed")
        self.assertEqual(self.jobs.get(second["job_id"])["state"], "queued")


    def test_worker_stages_a_verified_project_and_keeps_openfilm_cache_out_of_source(self):
        created = self.create_job("task-stage", "key-stage")
        original_html = (self.project / "film.html").read_text(encoding="utf-8")
        isolation, qa = FakeIsolation(), FakeQA()
        worker = MediaWorker(self.jobs, isolation, self.config, qa=qa)
        result = worker.run_once()
        self.assertEqual(result["status"], "ready_for_human_review")
        staged = isolation.project_snapshots[0]
        self.assertNotEqual(staged["path"], self.project)
        self.assertTrue(staged["cache_exists"])
        self.assertEqual(staged["film_html"], original_html)
        self.assertFalse((self.project / ".film").exists())
        self.assertFalse(staged["path"].exists())
        self.assertEqual(self.jobs.get(created["job_id"])["state"], "ready_for_human_review")


if __name__ == "__main__":
    unittest.main(verbosity=2)
