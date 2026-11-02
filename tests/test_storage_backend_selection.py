import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from unexpected_runtime.coordinator import Coordinator
from unexpected_runtime.providers import DeterministicMockProvider


class StorageBackendSelectionTests(unittest.TestCase):
    def test_hosted_database_mode_does_not_create_ephemeral_state_directory(self):
        class FakePostgresStore:
            backend = "postgresql"
            path = Path("postgresql")

        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            with patch.dict(os.environ, {"UNEXPECTED_DATABASE_URL": "postgresql://example.invalid/db"}):
                with patch("unexpected_runtime.coordinator.PostgresStateStore", return_value=FakePostgresStore()) as postgres:
                    coordinator = Coordinator(
                        state_dir=state_dir,
                        provider=DeterministicMockProvider(),
                        max_workers=1,
                    )
                    try:
                        self.assertIs(coordinator.store, postgres.return_value)
                        self.assertEqual(coordinator.store.backend, "postgresql")
                        self.assertFalse(state_dir.exists())
                    finally:
                        coordinator.close()

    def test_local_mode_still_creates_sqlite_state_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            with patch.dict(os.environ, {"UNEXPECTED_DATABASE_URL": ""}):
                coordinator = Coordinator(
                    state_dir=state_dir,
                    provider=DeterministicMockProvider(),
                    max_workers=1,
                )
                try:
                    self.assertEqual(coordinator.store.backend, "sqlite")
                    self.assertTrue(state_dir.is_dir())
                finally:
                    coordinator.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
