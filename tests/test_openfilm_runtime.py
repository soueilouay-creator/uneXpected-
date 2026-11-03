import tempfile
import unittest
from unittest.mock import patch

from unexpected_runtime.coordinator import Coordinator
from unexpected_runtime.capabilities import CapabilityRegistryError


class OpenFilmCoordinatorTests(unittest.TestCase):
    def test_openfilm_capability_is_discovered_and_worker_is_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as state_dir, patch.dict(
            "os.environ",
            {"UNEXPECTED_STORAGE_BACKEND": "sqlite", "UNEXPECTED_DEFAULT_PROVIDER": "mock"},
            clear=False,
        ):
            coordinator = Coordinator(state_dir=state_dir)
            try:
                self.assertEqual(len(coordinator.registry), 38)
                record = coordinator.capabilities.get("media.openfilm.render")
                self.assertEqual(record.status, "discovered")
                status = coordinator.media_status()
                self.assertFalse(status["worker_ready"])
                self.assertFalse(status["adapter_registered"])
                self.assertTrue(status["job_store_ready"])
                with self.assertRaises(CapabilityRegistryError):
                    coordinator.capabilities.transition(
                        "media.openfilm.render", "enabled", reason="must not enable without installation"
                    )
            finally:
                coordinator.close()

    def test_installed_adapter_uses_the_existing_mcp_gateway_and_four_existing_roles(self):
        with tempfile.TemporaryDirectory() as state_dir, patch.dict(
            "os.environ",
            {"UNEXPECTED_STORAGE_BACKEND": "sqlite", "UNEXPECTED_DEFAULT_PROVIDER": "mock"},
            clear=False,
        ):
            coordinator = Coordinator(state_dir=state_dir)
            try:
                record = coordinator.capabilities.get("media.openfilm.render")
                coordinator.capabilities.transition(
                    record.capability_id, "reviewed", reviewer="test-owner", reason="test source review"
                )
                coordinator.capabilities.transition(
                    record.capability_id, "installed", reason="test fixture installation"
                )
                coordinator.media_register_adapter()
                coordinator.capabilities.transition(
                    record.capability_id, "enabled", reason="test fixture enablement"
                )
                self.assertTrue(coordinator.media_status()["adapter_registered"])
                args = {
                    "task_id": "media-test-task",
                    "idempotency_key": "media-test-request",
                    "project_path": "pilot/film.html",
                    "campaign_id": "MAINTENANCE_TRACKER_GROWTH",
                    "content_id": "YT-TRACKER-TEST-01",
                    "synthetic_data": True,
                    "rights_manifest": {"sources": [{"kind": "original"}]},
                    "variants": [{"platform": "youtube_shorts", "width": 1080, "height": 1920}],
                }
                queued = coordinator.media_create_job(args)
                self.assertEqual(queued["state"], "queued")
                self.assertEqual(coordinator.media_status()["queued_jobs"], 1)
            finally:
                coordinator.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
