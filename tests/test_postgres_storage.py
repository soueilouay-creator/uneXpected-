from __future__ import annotations

import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

from unexpected_runtime.postgres_storage import PostgresStateStore, PostgresStorageError


class Cursor:
    def __init__(self, row=None, rowcount=0):
        self.row = row
        self.rowcount = rowcount
    def fetchone(self):
        return self.row
    def fetchall(self):
        return [] if self.row is None else [self.row]


class FakePostgres:
    def __init__(self, version=2):
        self.version = version
        self.lock = threading.Lock()
        self.claims = {}
        self.closed = 0

    def connect(self):
        return FakeConnection(self)


class FakeConnection:
    def __init__(self, db):
        self.db = db
    def execute(self, sql, params=()):
        if "SELECT version FROM schema_migrations" in sql:
            return Cursor({"version": self.db.version})
        if sql.strip() == "SELECT 1 AS ok":
            return Cursor({"ok": 1})
        if sql.startswith("INSERT INTO idempotency_claims"):
            key, request_hash, task_id, created, updated = params
            with self.db.lock:
                if key in self.db.claims:
                    return Cursor(None, 0)
                self.db.claims[key] = {
                    "request_hash": request_hash, "task_id": task_id, "state": "running",
                    "result_json": None, "updated_at": updated,
                }
                return Cursor({"idempotency_key": key}, 1)
        if sql.startswith("SELECT request_hash,task_id,state,result_json,updated_at FROM idempotency_claims"):
            key = params[0]
            with self.db.lock:
                row = self.db.claims.get(key)
                return Cursor(dict(row) if row else None)
        if sql.startswith("UPDATE idempotency_claims SET task_id="):
            task_id, updated, key, old_updated = params
            with self.db.lock:
                row = self.db.claims.get(key)
                if row and row["state"] == "running" and row["updated_at"] == old_updated:
                    row.update(task_id=task_id, updated_at=updated, result_json=None)
                    return Cursor({"task_id": task_id}, 1)
                return Cursor(None, 0)
        if sql.startswith("UPDATE idempotency_claims SET state="):
            state = "completed" if "state='completed'" in sql else "failed"
            result_json, updated, key, task_id = params
            with self.db.lock:
                row = self.db.claims.get(key)
                if row and row["task_id"] == task_id and row["state"] == "running":
                    row.update(state=state, result_json=result_json, updated_at=updated)
                    return Cursor(None, 1)
                return Cursor(None, 0)
        raise AssertionError("Unexpected SQL in fake Postgres test: " + sql)
    def commit(self):
        pass
    def rollback(self):
        pass
    def close(self):
        self.db.closed += 1


class PostgresStorageTests(unittest.TestCase):
    def test_requires_v8_schema_migration_and_does_not_create_tables(self):
        db = FakePostgres(version=1)
        with self.assertRaises(PostgresStorageError):
            PostgresStateStore("postgresql://unit.test/db", connect_factory=db.connect)
        self.assertEqual(db.claims, {})

    def test_checks_database_readiness(self):
        db = FakePostgres(version=2)
        store = PostgresStateStore("postgresql://unit.test/db", connect_factory=db.connect)
        self.assertTrue(store.check_health())
        self.assertEqual(store.backend, "postgres")

    def test_concurrent_idempotency_claims_have_one_owner(self):
        db = FakePostgres(version=2)
        store = PostgresStateStore("postgresql://unit.test/db", connect_factory=db.connect)
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(
                lambda index: store.claim_idempotency("key", "a" * 64, "task-" + str(index)),
                range(24),
            ))
        self.assertEqual(sum(result["state"] == "claimed" for result in results), 1)
        self.assertEqual(sum(result["state"] == "running" for result in results), 23)

    def test_completed_claim_replays_exact_result_and_rejects_changed_payload(self):
        db = FakePostgres(version=2)
        store = PostgresStateStore("postgresql://unit.test/db", connect_factory=db.connect)
        store.claim_idempotency("key", "a" * 64, "task-1")
        result = {"task_id": "task-1", "status": "completed", "output": "verified"}
        self.assertTrue(store.complete_idempotency("key", "task-1", result))
        replay = store.claim_idempotency("key", "a" * 64, "task-2")
        self.assertEqual(replay["state"], "completed")
        self.assertEqual(replay["result"], result)
        with self.assertRaises(ValueError):
            store.claim_idempotency("key", "b" * 64, "task-3")


if __name__ == "__main__":
    unittest.main(verbosity=2)
