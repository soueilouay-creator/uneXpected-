import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from unexpected_runtime.capabilities import CapabilityRegistryError
from unexpected_runtime.coordinator import Coordinator


class OpenFilmCoordinatorTests(unittest.TestCase):
    def test_openfilm_capability_is_discovered_but_not_enabled_or_registered(self):
        with tempfile.TemporaryDirectory() as state_dir, patch.dict(
            "os.environ",
            {"UNEXPECTED_STORAGE_BACKEND": "sqlite", "UNEXPECTED_DEFAULT_PROVIDER": "mock"},
            clear=False,
        ):
            coordinator = Coordinator(state_dir=state_dir)
            try:
                self.assertEqual(len(coordinator.registry), 38)
                record = coordinator.capability_registry.get("media.openfilm.render")
                self.assertEqual(record.status, "discovered")
                self.assertEqual(record.provider, "openfilm")
                status = coordinator.media_status()
                self.assertFalse(status["worker_ready"])
                self.assertFalse(status["available"])
                self.assertTrue(status["job_store_ready"])
                self.assertTrue(status["adapter_ready"])
                with self.assertRaises(CapabilityRegistryError):
                    coordinator.capability_registry.transition(
                        "media.openfilm.render", "reviewed",
                        reviewer="test-owner", reason="test lifecycle",
                    )
                self.assertEqual(coordinator.media_status()["status"], "discovered")
            finally:
                coordinator.close()

    def test_local_render_scope_is_granted_only_to_four_creative_roles(self):
        with tempfile.TemporaryDirectory() as state_dir:
            coordinator = Coordinator(state_dir=state_dir)
            try:
                allowed = {"orchestrator", "creative-director", "media-producer", "voice-agent"}
                actual = {
                    agent.id for agent in coordinator.registry.list()
                    if "media.local_render" in agent.allowed_permissions
                }
                self.assertEqual(actual, allowed)
            finally:
                coordinator.close()

    def test_read_only_media_status_cli_does_not_enable_capability(self):
        with tempfile.TemporaryDirectory() as state_dir, patch.dict(
            "os.environ",
            {
                "UNEXPECTED_STORAGE_BACKEND": "sqlite",
                "UNEXPECTED_STATE_DIR": state_dir,
                "UNEXPECTED_DEFAULT_PROVIDER": "mock",
            },
            clear=False,
        ):
            from unexpected_runtime.cli import main
            with patch("sys.stdout"):
                exit_code = main(["media", "status"])
            self.assertEqual(exit_code, 0)
            store = Coordinator(state_dir=state_dir)
            try:
                self.assertEqual(
                    store.capability_registry.get("media.openfilm.render").status,
                    "discovered",
                )
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
