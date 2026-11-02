import tempfile
import unittest
from pathlib import Path

from unexpected_runtime.storage import StateStore


class WorkspaceSyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self.tmp.name) / "state.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_import_is_additive_and_duplicate_replay_is_idempotent(self):
        record = {"id": "chat-1", "type": "conversation", "payload": {"messages": []}, "updated_at": "2026-11-02T10:00:00Z"}
        first = self.store.import_workspace_records("device-a", [record])
        second = self.store.import_workspace_records("device-a", [record])
        self.assertEqual(first, {"inserted": 1, "updated": 0, "duplicates": 0, "conflicts": 0})
        self.assertEqual(second, {"inserted": 0, "updated": 0, "duplicates": 1, "conflicts": 0})
        self.assertEqual(len(self.store.export_workspace_records()), 1)

    def test_same_device_newer_revision_keeps_prior_version_in_history(self):
        original = {"id": "project-1", "type": "project", "payload": {"name": "Old"}, "updated_at": "2026-11-02T10:00:00Z"}
        updated = {"id": "project-1", "type": "project", "payload": {"name": "New"}, "updated_at": "2026-11-02T11:00:00Z"}
        self.store.import_workspace_records("device-a", [original])
        counts = self.store.import_workspace_records("device-a", [updated])
        records = self.store.export_workspace_records()
        canonical = next(item for item in records if item["id"] == "project-1")
        history = [item for item in records if item["id"].startswith("history-")]
        self.assertEqual(counts, {"inserted": 0, "updated": 1, "duplicates": 0, "conflicts": 0})
        self.assertEqual(canonical["payload"], {"name": "New"})
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["payload"]["record"], {"name": "Old"})

    def test_changed_record_from_another_device_is_preserved_as_conflict(self):
        original = {"id": "memory-1", "type": "memory", "payload": {"content": "A"}, "updated_at": "2026-11-02T10:00:00Z"}
        other = {"id": "memory-1", "type": "memory", "payload": {"content": "B"}, "updated_at": "2026-11-02T11:00:00Z"}
        self.store.import_workspace_records("device-a", [original])
        counts = self.store.import_workspace_records("device-b", [other])
        records = self.store.export_workspace_records()
        canonical = next(item for item in records if item["id"] == "memory-1")
        conflicts = [item for item in records if item["id"].startswith("conflict-")]
        self.assertEqual(counts, {"inserted": 0, "updated": 0, "duplicates": 0, "conflicts": 1})
        self.assertEqual(canonical["payload"], {"content": "A"})
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["payload"]["record"], {"content": "B"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
