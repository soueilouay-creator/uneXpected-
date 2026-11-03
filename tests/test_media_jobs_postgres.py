from __future__ import annotations

import os
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from unexpected_runtime.media.jobs import MediaJobService
from unexpected_runtime.postgres_storage import PostgresStateStore


DSN = os.getenv("TEST_POSTGRES_DSN")


@unittest.skipUnless(DSN, "TEST_POSTGRES_DSN is only provided by the ephemeral CI PostgreSQL service")
class MediaJobPostgresIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.store = PostgresStateStore(DSN)
        self.jobs = MediaJobService(self.store)
        self.prefix = "media-ci-" + __import__("uuid").uuid4().hex

    def test_postgres_idempotency_single_flight_claim_and_lease_fencing(self):
        first = self.jobs.create(
            task_id=self.prefix,
            idempotency_key="render",
            request={"project": "synthetic/film.html", "variant": {"width": 1080, "height": 1920}},
        )
        replay = self.jobs.create(
            task_id=self.prefix,
            idempotency_key="render",
            request={"project": "synthetic/film.html", "variant": {"width": 1080, "height": 1920}},
        )
        self.assertEqual(first["job_id"], replay["job_id"])
        self.assertTrue(replay["replayed"])

        barrier = threading.Barrier(16)
        def claim(index):
            barrier.wait(timeout=10)
            return self.jobs.claim_one(f"pg-worker-{index}", lease_seconds=60)

        with ThreadPoolExecutor(max_workers=16) as pool:
            claims = list(pool.map(claim, range(16)))
        winners = [item for item in claims if item is not None]
        self.assertEqual(len(winners), 1)
        owner = winners[0]
        self.assertEqual(owner["job_id"], first["job_id"])
        self.assertTrue(self.jobs.advance(
            owner["job_id"], expected_state="claimed", target_state="inspecting",
            worker_id=owner["lease_owner"], lease_token=owner["lease_token"],
        ))
        self.assertFalse(self.jobs.advance(
            owner["job_id"], expected_state="inspecting", target_state="rendering",
            worker_id=owner["lease_owner"], lease_token="old-fenced-token",
        ))

    def tearDown(self):
        self.store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
