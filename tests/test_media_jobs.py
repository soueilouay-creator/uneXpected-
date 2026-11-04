import json
import tempfile
import threading
import unittest
from pathlib import Path

from unexpected_runtime.media.jobs import MediaJobConflict, MediaJobService
from unexpected_runtime.storage import StateStore


class MediaJobServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "state.sqlite3"
        self.store = StateStore(self.path)
        self.jobs = MediaJobService(self.store)

    def tearDown(self):
        self.temp.cleanup()

    def create(self, *, task_id="task-1", key="request-1", request=None):
        return self.jobs.create(
            task_id=task_id,
            idempotency_key=key,
            request=request or {"project": "demo/film.html", "variants": [{"width": 1080, "height": 1920}]},
        )

    def test_create_is_idempotent_and_changed_payload_conflicts(self):
        first = self.create()
        replay = self.create()
        self.assertEqual(first["job_id"], replay["job_id"])
        self.assertTrue(replay["replayed"])
        with self.assertRaises(MediaJobConflict):
            self.create(request={"project": "other/film.html"})

    def test_concurrent_claims_have_exactly_one_owner(self):
        self.create()
        claimed = []
        failures = []
        barrier = threading.Barrier(12)

        def claim(index):
            try:
                barrier.wait(timeout=5)
                item = self.jobs.claim_one(f"worker-{index}", lease_seconds=30)
                if item:
                    claimed.append(item)
            except Exception as exc:
                failures.append(exc)

        threads = [threading.Thread(target=claim, args=(i,)) for i in range(12)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)
        self.assertFalse(failures)
        self.assertEqual(len(claimed), 1)
        self.assertEqual(claimed[0]["state"], "claimed")
        self.assertTrue(claimed[0]["lease_token"])

    def test_stale_lease_cannot_advance_job(self):
        self.create()
        claimed = self.jobs.claim_one("worker-a", lease_seconds=30)
        self.assertTrue(self.jobs.advance(
            claimed["job_id"], expected_state="claimed", target_state="inspecting",
            worker_id="worker-a", lease_token=claimed["lease_token"],
        ))
        self.assertFalse(self.jobs.advance(
            claimed["job_id"], expected_state="inspecting", target_state="rendering",
            worker_id="worker-a", lease_token="stale-token",
        ))

    def test_expired_lease_retry_fences_old_worker(self):
        self.create()
        claimed = self.jobs.claim_one("worker-a", lease_seconds=0.05)
        import time
        time.sleep(0.08)
        recovered = self.jobs.recover_expired(
            claimed["job_id"], old_lease_token=claimed["lease_token"],
            worker_id="worker-b", lease_seconds=30, recovery_action="retry",
        )
        self.assertEqual(recovered["state"], "queued")
        self.assertIsNone(recovered["lease_token"])
        self.assertFalse(self.jobs.advance(
            claimed["job_id"], expected_state="claimed", target_state="inspecting",
            worker_id="worker-a", lease_token=claimed["lease_token"],
        ))

    def test_cancel_queued_and_running_jobs(self):
        queued = self.create(task_id="task-queued", key="queued")
        self.assertEqual(self.jobs.cancel(queued["job_id"]), "cancelled")
        active = self.create(task_id="task-active", key="active")
        claimed = self.jobs.claim_one("worker-a", lease_seconds=30)
        self.assertEqual(active["job_id"], claimed["job_id"])
        self.assertEqual(self.jobs.cancel(active["job_id"]), "cancel_requested")

    def test_invalid_transition_is_rejected_and_listing_is_bounded(self):
        first = self.create()
        with self.assertRaises(ValueError):
            self.jobs.advance(
                first["job_id"], expected_state="queued", target_state="rendering",
                worker_id=None, lease_token=None,
            )
        self.assertEqual(len(self.jobs.list(limit=1)), 1)

    def test_state_persists_after_reopen(self):
        created = self.create()
        claimed = self.jobs.claim_one("worker-a", lease_seconds=30)
        self.assertEqual(created["job_id"], claimed["job_id"])
        reopened = MediaJobService(StateStore(self.path)).get(created["job_id"])
        self.assertEqual(reopened["state"], "claimed")
        self.assertEqual(reopened["attempt_count"], 1)
        self.assertEqual(json.loads(reopened["request_json"])["project"], "demo/film.html")


if __name__ == "__main__":
    unittest.main(verbosity=2)
