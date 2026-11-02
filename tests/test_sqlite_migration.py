import tempfile
import unittest
from pathlib import Path

from migrate_sqlite_to_postgres import _digest, migrate


class SQLiteMigrationUtilityTests(unittest.TestCase):
    def test_digest_is_deterministic_for_ordered_rows(self):
        self.assertEqual(_digest([(1, "a"), (2, "b")]), _digest([(1, "a"), (2, "b")]))
        self.assertNotEqual(_digest([(1, "a"), (2, "b")]), _digest([(2, "b"), (1, "a")]))

    def test_missing_source_is_rejected_before_any_database_connection(self):
        with self.assertRaises(FileNotFoundError):
            migrate(Path("/missing/uneXpected.sqlite3"), "postgresql://invalid")

    def test_non_postgresql_target_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.sqlite3"
            source.touch()
            with self.assertRaises(ValueError):
                migrate(source, "sqlite:///not-postgres.db")


if __name__ == "__main__":
    unittest.main(verbosity=2)
