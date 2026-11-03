from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class OpenFilmMigrationContractTests(unittest.TestCase):
    def test_media_job_migration_is_additive_and_versioned_after_prompt_intelligence(self):
        migration = (ROOT / "migrations" / "004_openfilm_media_jobs.sql").read_text(encoding="utf-8").lower()
        self.assertIn("create table if not exists media_jobs", migration)
        self.assertIn("unique (task_id, idempotency_key)", migration)
        self.assertIn("'ready_for_human_review'", migration)
        self.assertIn("values (4, '004_openfilm_media_jobs.sql'", migration)
        self.assertNotIn("drop table", migration)
        self.assertNotIn("truncate", migration)


if __name__ == "__main__":
    unittest.main(verbosity=2)
