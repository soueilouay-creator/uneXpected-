from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Iterator
from urllib.parse import urlsplit
from .postgres_idempotency import PostgresIdempotencyMixin
import json
import time
import uuid


class PostgresStorageError(RuntimeError):
    pass


class PostgresStateStore(PostgresIdempotencyMixin):
    """PostgreSQL implementation of the runtime StateStore contract.

    The schema is managed by checked-in migrations. This class never creates,
    drops, or silently repairs production tables.
    """

    backend = "postgres"

    def __init__(self, dsn: str, *, connect_factory: Callable[[], Any] | None = None,
                 validate_schema: bool = True):
        parsed = urlsplit(str(dsn or "").strip())
        if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname:
            raise PostgresStorageError("A valid PostgreSQL DATABASE_URL is required.")
        self._dsn = str(dsn).strip()
        self._connect_factory = connect_factory
        if validate_schema:
            try:
                with self._session() as connection:
                    row = connection.execute(
                        "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
                    ).fetchone()
                    if not row or int(row["version"]) < 3:
                        raise PostgresStorageError("PostgreSQL v8 migrations are not initialized; migration 003 is required.")
            except PostgresStorageError:
                raise
            except Exception as exc:
                raise PostgresStorageError(
                    f"PostgreSQL schema check failed ({type(exc).__name__}); no local fallback was used."
                ) from None

    def _connect(self):
        if self._connect_factory is not None:
            return self._connect_factory()
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError:
            raise PostgresStorageError("psycopg 3 is required for PostgreSQL storage.") from None
        try:
            return psycopg.connect(self._dsn, row_factory=dict_row, connect_timeout=5)
        except Exception as exc:
            raise PostgresStorageError(
                f"PostgreSQL connection failed ({type(exc).__name__}); credentials were not disclosed."
            ) from None

    @contextmanager
    def _session(self) -> Iterator[Any]:
        connection = self._connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            try:
                connection.rollback()
            finally:
                raise
        finally:
            connection.close()

    @staticmethod
    def _dump(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)

    @staticmethod
    def _bounded(limit: int, maximum: int = 1000) -> int:
        return max(1, min(int(limit), maximum))

    def close(self):
        return None

    def check_health(self) -> bool:
        with self._session() as connection:
            row = connection.execute("SELECT 1 AS ok").fetchone()
            return bool(row and row.get("ok") == 1)

    def log_event(self, event_type: str, task_id: str | None = None,
                  agent_id: str | None = None, payload: dict[str, Any] | None = None):
        with self._session() as connection:
            connection.execute(
                "INSERT INTO events(ts,task_id,agent_id,event_type,payload_json) VALUES(%s,%s,%s,%s,%s)",
                (time.time(), task_id, agent_id, event_type, self._dump(payload or {})),
            )

    def events(self, limit: int = 100):
        with self._session() as connection:
            rows = connection.execute(
                "SELECT event_id,ts,task_id,agent_id,event_type,payload_json FROM events ORDER BY event_id DESC LIMIT %s",
                (self._bounded(limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_task_events(self, task_id: str, *, after_event_id: int = 0, limit: int = 100):
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string.")
        if isinstance(after_event_id, bool) or not isinstance(after_event_id, int) or after_event_id < 0:
            raise ValueError("after_event_id must be a non-negative integer.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 201:
            raise ValueError("limit must be an integer between 1 and 201.")
        with self._session() as connection:
            rows = connection.execute(
                "SELECT event_id,ts,task_id,agent_id,event_type,payload_json FROM events "
                "WHERE task_id=%s AND event_id>%s ORDER BY event_id ASC LIMIT %s",
                (task_id, after_event_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def enqueue(self, request):
        payload = {
            "task_id": request.task_id, "agent_id": request.agent_id,
            "objective": request.objective, "inputs": request.inputs,
            "required_permissions": list(request.required_permissions),
            "deadline_seconds": request.deadline_seconds, "max_steps": request.max_steps,
            "idempotency_key": request.idempotency_key, "source_refs": list(request.source_refs),
            "provider_route": getattr(request, "provider_route", None),
            "requested_skill_ids": list(getattr(request, "requested_skill_ids", ())),
            "parent_task_id": getattr(request, "parent_task_id", None),
            "created_at": request.created_at,
        }
        now = time.time()
        with self._session() as connection:
            connection.execute(
                "INSERT INTO tasks(task_id,agent_id,status,payload_json,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s)",
                (request.task_id, request.agent_id, "queued", self._dump(payload), now, now),
            )
            connection.execute(
                "INSERT INTO events(ts,task_id,agent_id,event_type,payload_json) VALUES(%s,%s,%s,%s,%s)",
                (now, request.task_id, request.agent_id, "task_queued",
                 self._dump({"objective": request.objective[:160]})),
            )

    def get_task(self, task_id: str):
        with self._session() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE task_id=%s", (task_id,)).fetchone()
        return dict(row) if row else None

    def mark_task(self, task_id: str, status: str, result: dict[str, Any] | None = None) -> bool:
        with self._session() as connection:
            cursor = connection.execute(
                "UPDATE tasks SET status=%s,result_json=%s,updated_at=%s "
                "WHERE task_id=%s AND status NOT IN ('completed','failed','cancelled','timeout')",
                (status, self._dump(result) if result is not None else None, time.time(), task_id),
            )
        return cursor.rowcount == 1
    def mark_task_timeout(self, task_id: str, result: dict[str, Any]) -> bool:
        with self._session() as connection:
            cursor = connection.execute(
                "UPDATE tasks SET status='timeout',result_json=%s,updated_at=%s WHERE task_id=%s AND status!='completed'",
                (self._dump(result), time.time(), task_id),
            )
        return cursor.rowcount == 1

    def claim_next(self):
        with self._session() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE status='queued' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED"
            ).fetchone()
            if not row:
                return None
            cursor = connection.execute(
                "UPDATE tasks SET status='running',updated_at=%s WHERE task_id=%s AND status='queued'",
                (time.time(), row["task_id"]),
            )
            if cursor.rowcount != 1:
                return None
            result = dict(row)
            result["status"] = "running"
            return result

    def set_memory(self, agent_id: str, key: str, value: Any):
        with self._session() as connection:
            connection.execute(
                "INSERT INTO agent_memory(agent_id,key,value_json,updated_at) VALUES(%s,%s,%s,%s) "
                "ON CONFLICT(agent_id,key) DO UPDATE SET value_json=EXCLUDED.value_json,updated_at=EXCLUDED.updated_at",
                (agent_id, key, self._dump(value), time.time()),
            )

    def get_memory(self, agent_id: str, key: str, default=None):
        with self._session() as connection:
            row = connection.execute(
                "SELECT value_json FROM agent_memory WHERE agent_id=%s AND key=%s", (agent_id, key)
            ).fetchone()
        return json.loads(row["value_json"]) if row else default

    def memory_keys(self, agent_id: str):
        with self._session() as connection:
            rows = connection.execute(
                "SELECT key FROM agent_memory WHERE agent_id=%s ORDER BY key", (agent_id,)
            ).fetchall()
        return [row["key"] for row in rows]

    def get_idempotent(self, key: str, request_hash: str):
        with self._session() as connection:
            row = connection.execute(
                "SELECT request_hash,result_json FROM idempotency WHERE idempotency_key=%s", (key,)
            ).fetchone()
        if not row:
            return None
        if row["request_hash"] != request_hash:
            raise ValueError("Idempotency key reused with a different request payload.")
        return json.loads(row["result_json"])

    def set_idempotent(self, key: str, request_hash: str, result: dict[str, Any]):
        with self._session() as connection:
            connection.execute(
                "INSERT INTO idempotency(idempotency_key,request_hash,result_json,created_at) VALUES(%s,%s,%s,%s) "
                "ON CONFLICT(idempotency_key) DO NOTHING",
                (key, request_hash, self._dump(result), time.time()),
            )

    def add_knowledge(self, source: str, content: str):
        knowledge_id = str(uuid.uuid4())
        with self._session() as connection:
            connection.execute(
                "INSERT INTO shared_knowledge(knowledge_id,source,content,trust_status,created_at) VALUES(%s,%s,%s,%s,%s)",
                (knowledge_id, source, content, "pending", time.time()),
            )
            connection.execute(
                "INSERT INTO events(ts,event_type,payload_json) VALUES(%s,%s,%s)",
                (time.time(), "knowledge_pending", self._dump({"knowledge_id": knowledge_id, "source": source})),
            )
        return knowledge_id

    def approve_knowledge(self, knowledge_id: str, approved_by: str):
        if not approved_by:
            raise PermissionError("Shared knowledge requires a verified reviewer identity.")
        with self._session() as connection:
            cursor = connection.execute(
                "UPDATE shared_knowledge SET trust_status='approved',reviewed_by=%s WHERE knowledge_id=%s",
                (approved_by, knowledge_id),
            )
            if cursor.rowcount != 1:
                raise ValueError(f"Unknown shared knowledge record: {knowledge_id}")
            connection.execute(
                "INSERT INTO events(ts,event_type,payload_json) VALUES(%s,%s,%s)",
                (time.time(), "knowledge_approved",
                 self._dump({"knowledge_id": knowledge_id, "approved_by": approved_by})),
            )

    def query_knowledge(self, limit: int = 20):
        with self._session() as connection:
            rows = connection.execute(
                "SELECT knowledge_id,source,content,reviewed_by,created_at FROM shared_knowledge "
                "WHERE trust_status='approved' ORDER BY created_at DESC LIMIT %s",
                (self._bounded(limit, 100),),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_outcome(self, agent_id: str, task_id: str | None, success: bool,
                       feedback: str, provenance: list[str]):
        outcome_id = str(uuid.uuid4())
        now = time.time()
        with self._session() as connection:
            connection.execute(
                "INSERT INTO outcomes(outcome_id,agent_id,task_id,success,feedback,provenance_json,created_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s)",
                (outcome_id, agent_id, task_id, int(success), feedback, self._dump(provenance), now),
            )
            connection.execute(
                "INSERT INTO events(ts,task_id,agent_id,event_type,payload_json) VALUES(%s,%s,%s,%s,%s)",
                (now, task_id, agent_id, "outcome_recorded",
                 self._dump({"outcome_id": outcome_id, "success": success, "feedback": feedback[:160]})),
            )
        return outcome_id

    def set_baseline(self, agent_id: str, benchmark_id: str, report: dict[str, Any], *,
                     active_version: str | None = None, instruction_sha256: str | None = None,
                     report_sha256: str | None = None):
        with self._session() as connection:
            connection.execute(
                "INSERT INTO baselines(agent_id,benchmark_id,report_json,created_at,active_version,instruction_sha256,report_sha256) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(agent_id,benchmark_id) DO UPDATE SET "
                "report_json=EXCLUDED.report_json,created_at=EXCLUDED.created_at,active_version=EXCLUDED.active_version,"
                "instruction_sha256=EXCLUDED.instruction_sha256,report_sha256=EXCLUDED.report_sha256",
                (agent_id, benchmark_id, self._dump(report), time.time(), active_version,
                 instruction_sha256, report_sha256),
            )

    def get_baseline(self, agent_id: str, benchmark_id: str):
        with self._session() as connection:
            row = connection.execute(
                "SELECT report_json FROM baselines WHERE agent_id=%s AND benchmark_id=%s",
                (agent_id, benchmark_id),
            ).fetchone()
        return json.loads(row["report_json"]) if row else None

    def get_baseline_evidence(self, agent_id: str, benchmark_id: str):
        with self._session() as connection:
            row = connection.execute(
                "SELECT active_version,instruction_sha256,report_sha256 FROM baselines "
                "WHERE agent_id=%s AND benchmark_id=%s", (agent_id, benchmark_id)
            ).fetchone()
        return dict(row) if row else None

    def save_proposal(self, proposal: dict[str, Any]):
        now = time.time()
        with self._session() as connection:
            connection.execute(
                "INSERT INTO proposals(proposal_id,agent_id,base_version,candidate_version,candidate_instruction,changes,"
                "protected_change,benchmark_id,status,evaluation_json,created_at,protected_fields_json,evaluation_context_json) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (proposal["proposal_id"], proposal["agent_id"], proposal["base_version"],
                 proposal["candidate_version"], proposal["candidate_instruction"], proposal["changes"],
                 int(proposal["protected_change"]), proposal["benchmark_id"], proposal["status"],
                 self._dump(proposal["evaluation"]) if proposal.get("evaluation") else None, now,
                 self._dump(proposal.get("protected_fields", [])),
                 self._dump(proposal.get("evaluation_context", {}))),
            )
            connection.execute(
                "INSERT INTO events(ts,agent_id,event_type,payload_json) VALUES(%s,%s,%s,%s)",
                (now, proposal["agent_id"], "improvement_proposed",
                 self._dump({"proposal_id": proposal["proposal_id"], "base_version": proposal["base_version"],
                             "candidate_version": proposal["candidate_version"],
                             "protected_change": proposal["protected_change"]})),
            )

    def get_proposal(self, proposal_id: str):
        with self._session() as connection:
            row = connection.execute("SELECT * FROM proposals WHERE proposal_id=%s", (proposal_id,)).fetchone()
        if not row:
            return None
        item = dict(row)
        item["protected_change"] = bool(item["protected_change"])
        item["evaluation"] = json.loads(item.pop("evaluation_json")) if item.get("evaluation_json") else None
        item["protected_fields"] = json.loads(item.pop("protected_fields_json") or "[]")
        item["evaluation_context"] = json.loads(item.pop("evaluation_context_json") or "{}")
        return item

    def list_proposals(self, limit: int = 100):
        bounded = self._bounded(limit, 200)
        with self._session() as connection:
            rows = connection.execute(
                "SELECT * FROM proposals ORDER BY created_at DESC LIMIT %s", (bounded,)
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["protected_change"] = bool(item["protected_change"])
            item["evaluation"] = json.loads(item.pop("evaluation_json")) if item.get("evaluation_json") else None
            item["protected_fields"] = json.loads(item.pop("protected_fields_json") or "[]")
            item["evaluation_context"] = json.loads(item.pop("evaluation_context_json") or "{}")
            item.pop("candidate_instruction", None)
            return_item = item
            items.append(return_item)
        return items

    def update_proposal(self, proposal_id: str, status: str, evaluation: dict[str, Any] | None = None):
        with self._session() as connection:
            connection.execute(
                "UPDATE proposals SET status=%s,evaluation_json=%s WHERE proposal_id=%s",
                (status, self._dump(evaluation) if evaluation else None, proposal_id),
            )
            connection.execute(
                "INSERT INTO events(ts,event_type,payload_json) VALUES(%s,%s,%s)",
                (time.time(), "improvement_" + status,
                 self._dump({"proposal_id": proposal_id, "evaluation": evaluation or {}})),
            )

    def ensure_base_version(self, agent_id: str, version: str, instruction: str):
        with self._session() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (agent_id,))
            row = connection.execute(
                "SELECT version FROM agent_versions WHERE agent_id=%s AND active=1 FOR UPDATE",
                (agent_id,),
            ).fetchone()
            if not row:
                connection.execute(
                    "INSERT INTO agent_versions(agent_id,version,instruction,change_log,active,created_at) "
                    "VALUES(%s,%s,%s,%s,0,%s) ON CONFLICT(agent_id,version) DO NOTHING",
                    (agent_id, version, instruction, "baseline", time.time()),
                )
                connection.execute("UPDATE agent_versions SET active=1 WHERE agent_id=%s AND version=%s",
                                   (agent_id, version))

    def active_version(self, agent_id: str, default_version: str, default_instruction: str):
        self.ensure_base_version(agent_id, default_version, default_instruction)
        with self._session() as connection:
            row = connection.execute(
                "SELECT version,instruction FROM agent_versions WHERE agent_id=%s AND active=1",
                (agent_id,),
            ).fetchone()
        if not row:
            raise PostgresStorageError("No active agent version is available.")
        return dict(row)

    def promote_version(self, agent_id: str, version: str, instruction: str, change_log: str):
        with self._session() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (agent_id,))
            connection.execute("UPDATE agent_versions SET active=0 WHERE agent_id=%s", (agent_id,))
            connection.execute(
                "INSERT INTO agent_versions(agent_id,version,instruction,change_log,active,created_at) "
                "VALUES(%s,%s,%s,%s,1,%s) ON CONFLICT(agent_id,version) DO UPDATE SET "
                "instruction=EXCLUDED.instruction,change_log=EXCLUDED.change_log,active=1",
                (agent_id, version, instruction, change_log, time.time()),
            )
            connection.execute(
                "INSERT INTO events(ts,agent_id,event_type,payload_json) VALUES(%s,%s,%s,%s)",
                (time.time(), agent_id, "version_promoted",
                 self._dump({"version": version, "change_log": change_log})),
            )

    def rollback_version(self, agent_id: str, target_version: str, reason: str):
        with self._session() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (agent_id,))
            row = connection.execute(
                "SELECT 1 FROM agent_versions WHERE agent_id=%s AND version=%s",
                (agent_id, target_version),
            ).fetchone()
            if not row:
                raise ValueError(f"Unknown rollback target version {target_version}")
            connection.execute("UPDATE agent_versions SET active=0 WHERE agent_id=%s", (agent_id,))
            connection.execute(
                "UPDATE agent_versions SET active=1 WHERE agent_id=%s AND version=%s",
                (agent_id, target_version),
            )
            connection.execute(
                "INSERT INTO events(ts,agent_id,event_type,payload_json) VALUES(%s,%s,%s,%s)",
                (time.time(), agent_id, "version_rollback",
                 self._dump({"target_version": target_version, "reason": reason})),
            )

    def versions(self, agent_id: str):
        with self._session() as connection:
            rows = connection.execute(
                "SELECT version,change_log,active,created_at FROM agent_versions WHERE agent_id=%s ORDER BY created_at",
                (agent_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_capability(self, record: dict[str, Any]):
        now = time.time()
        with self._session() as connection:
            connection.execute(
                "INSERT INTO capabilities(capability_id,status,record_json,created_at,updated_at) VALUES(%s,%s,%s,%s,%s)",
                (record["capability_id"], record["status"], self._dump(record), now, now),
            )

    def get_capability(self, capability_id: str):
        with self._session() as connection:
            row = connection.execute(
                "SELECT record_json FROM capabilities WHERE capability_id=%s", (capability_id,)
            ).fetchone()
        return json.loads(row["record_json"]) if row else None

    def list_capabilities(self, status: str | None = None):
        with self._session() as connection:
            if status is None:
                rows = connection.execute(
                    "SELECT record_json FROM capabilities ORDER BY created_at,capability_id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT record_json FROM capabilities WHERE status=%s ORDER BY created_at,capability_id",
                    (status,),
                ).fetchall()
        return [json.loads(row["record_json"]) for row in rows]

    def update_capability(self, record: dict[str, Any], expected_status: str) -> bool:
        with self._session() as connection:
            cursor = connection.execute(
                "UPDATE capabilities SET status=%s,record_json=%s,updated_at=%s WHERE capability_id=%s AND status=%s",
                (record["status"], self._dump(record), time.time(), record["capability_id"], expected_status),
            )
        return cursor.rowcount == 1


    # Prompt Intelligence methods mirror the SQLite StateStore contract.
    def create_prompt_source(self, record: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        with self._session() as connection:
            connection.execute(
                "INSERT INTO prompt_sources(source_id,status,record_json,created_at,updated_at) VALUES(%s,%s,%s,%s,%s)",
                (record["source_id"], record["status"], self._dump(record), now, now),
            )
        return dict(record)

    def get_prompt_source(self, source_id: str):
        with self._session() as connection:
            row = connection.execute(
                "SELECT record_json FROM prompt_sources WHERE source_id=%s", (source_id,)
            ).fetchone()
        return json.loads(row["record_json"]) if row else None

    def list_prompt_sources(self, limit: int = 50):
        with self._session() as connection:
            rows = connection.execute(
                "SELECT record_json FROM prompt_sources ORDER BY created_at DESC,source_id LIMIT %s",
                (self._bounded(limit, 200),),
            ).fetchall()
        return [json.loads(row["record_json"]) for row in rows]

    def update_prompt_source(self, record: dict[str, Any], expected_status: str) -> bool:
        with self._session() as connection:
            cursor = connection.execute(
                "UPDATE prompt_sources SET status=%s,record_json=%s,updated_at=%s WHERE source_id=%s AND status=%s",
                (record["status"], self._dump(record), time.time(), record["source_id"], expected_status),
            )
        return cursor.rowcount == 1

    def stage_prompt_versions(self, records: list[tuple[dict[str, Any], dict[str, Any]]]):
        created = 0
        duplicates = 0
        results = []
        with self._session() as connection:
            for prompt_record, version_record in records:
                source = connection.execute(
                    "SELECT source_id FROM prompt_sources WHERE source_id=%s",
                    (prompt_record["source_id"],),
                ).fetchone()
                if not source:
                    raise ValueError("Prompt source does not exist.")
                existing = connection.execute(
                    "SELECT * FROM prompts WHERE source_id=%s AND external_id=%s FOR UPDATE",
                    (prompt_record["source_id"], prompt_record["external_id"]),
                ).fetchone()
                if existing:
                    same = connection.execute(
                        "SELECT version FROM prompt_versions WHERE prompt_id=%s AND content_sha256=%s ORDER BY version DESC LIMIT 1",
                        (existing["prompt_id"], version_record["content_sha256"]),
                    ).fetchone()
                    if same:
                        duplicates += 1
                        result = dict(existing)
                        result["version"] = int(same["version"])
                        result["created"] = False
                        results.append(result)
                        continue
                    next_row = connection.execute(
                        "SELECT COALESCE(MAX(version),0)+1 AS next_version FROM prompt_versions WHERE prompt_id=%s",
                        (existing["prompt_id"],),
                    ).fetchone()
                    version = int(next_row["next_version"])
                    prompt_id = existing["prompt_id"]
                    prompt_status = "active" if existing["active_version"] is not None else "staged"
                    connection.execute(
                        "UPDATE prompts SET title=%s,category=%s,category_id=%s,status=%s,candidate_version=%s,updated_at=%s WHERE prompt_id=%s",
                        (prompt_record["title"], prompt_record["category"], prompt_record["category_id"],
                         prompt_status, version, time.time(), prompt_id),
                    )
                else:
                    prompt_id = prompt_record["prompt_id"]
                    version = 1
                    now = time.time()
                    connection.execute(
                        "INSERT INTO prompts(prompt_id,source_id,external_id,title,category,category_id,status,active_version,candidate_version,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,NULL,%s,%s,%s)",
                        (prompt_id, prompt_record["source_id"], prompt_record["external_id"],
                         prompt_record["title"], prompt_record["category"], prompt_record["category_id"],
                         "staged", version, now, now),
                    )
                payload = dict(version_record)
                payload["prompt_id"] = prompt_id
                payload["version"] = version
                payload["status"] = "staged"
                connection.execute(
                    "INSERT INTO prompt_versions(prompt_id,version,status,content_sha256,body,record_json,created_at,reviewed_at) VALUES(%s,%s,%s,%s,%s,%s,%s,NULL)",
                    (prompt_id, version, "staged", payload["content_sha256"], payload.get("body"),
                     self._dump(payload), time.time()),
                )
                row = connection.execute(
                    "SELECT * FROM prompts WHERE prompt_id=%s", (prompt_id,)
                ).fetchone()
                result = dict(row)
                result["version"] = version
                result["created"] = True
                results.append(result)
                created += 1
        return {"created": created, "duplicates": duplicates, "items": results}

    def get_prompt(self, prompt_id: str):
        with self._session() as connection:
            row = connection.execute("SELECT * FROM prompts WHERE prompt_id=%s", (prompt_id,)).fetchone()
        return dict(row) if row else None

    def get_prompt_version(self, prompt_id: str, version: int):
        with self._session() as connection:
            row = connection.execute(
                "SELECT * FROM prompt_versions WHERE prompt_id=%s AND version=%s",
                (prompt_id, version),
            ).fetchone()
        if not row:
            return None
        payload = json.loads(row["record_json"])
        payload.update({
            "prompt_id": row["prompt_id"], "version": int(row["version"]),
            "status": row["status"], "content_sha256": row["content_sha256"],
            "body": row["body"],
        })
        return payload

    def update_prompt_version(self, record: dict[str, Any], expected_status: str) -> bool:
        reviewed_at = record.get("review", {}).get("reviewed_at")
        with self._session() as connection:
            cursor = connection.execute(
                "UPDATE prompt_versions SET status=%s,record_json=%s,reviewed_at=%s WHERE prompt_id=%s AND version=%s AND status=%s",
                (record["status"], self._dump(record), reviewed_at, record["prompt_id"],
                 int(record["version"]), expected_status),
            )
            if cursor.rowcount != 1:
                return False
            connection.execute(
                "UPDATE prompts SET candidate_version=%s,status=CASE WHEN active_version IS NULL THEN 'staged' ELSE 'active' END,updated_at=%s WHERE prompt_id=%s",
                (int(record["version"]), time.time(), record["prompt_id"]),
            )
        return True

    def activate_prompt_version(self, prompt_id: str, version: int, expected_candidate_version: int):
        now = time.time()
        with self._session() as connection:
            prompt = connection.execute(
                "SELECT * FROM prompts WHERE prompt_id=%s FOR UPDATE", (prompt_id,)
            ).fetchone()
            if not prompt or prompt["candidate_version"] != expected_candidate_version:
                return None
            version_row = connection.execute(
                "SELECT * FROM prompt_versions WHERE prompt_id=%s AND version=%s FOR UPDATE",
                (prompt_id, version),
            ).fetchone()
            if not version_row or version_row["status"] != "ready_for_activation":
                return None
            previous = prompt["active_version"]
            if previous is not None and int(previous) != int(version):
                old = connection.execute(
                    "SELECT record_json FROM prompt_versions WHERE prompt_id=%s AND version=%s",
                    (prompt_id, int(previous)),
                ).fetchone()
                if old:
                    old_payload = json.loads(old["record_json"])
                    old_payload["status"] = "superseded"
                    connection.execute(
                        "UPDATE prompt_versions SET status='superseded',record_json=%s WHERE prompt_id=%s AND version=%s",
                        (self._dump(old_payload), prompt_id, int(previous)),
                    )
            payload = json.loads(version_row["record_json"])
            payload["status"] = "active"
            payload["activated_at"] = now
            connection.execute(
                "UPDATE prompt_versions SET status='active',record_json=%s WHERE prompt_id=%s AND version=%s AND status='ready_for_activation'",
                (self._dump(payload), prompt_id, int(version)),
            )
            cursor = connection.execute(
                "UPDATE prompts SET status='active',active_version=%s,candidate_version=NULL,title=%s,category=%s,category_id=%s,updated_at=%s WHERE prompt_id=%s AND candidate_version=%s",
                (int(version), payload["title"], payload["category"], payload["category_id"],
                 now, prompt_id, expected_candidate_version),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Prompt candidate changed during activation.")
            result = dict(connection.execute(
                "SELECT * FROM prompts WHERE prompt_id=%s", (prompt_id,)
            ).fetchone())
        return result

    def get_active_prompt(self, prompt_id: str):
        with self._session() as connection:
            row = connection.execute(
                "SELECT p.*,v.record_json,v.body,v.content_sha256 FROM prompts p "
                "JOIN prompt_versions v ON v.prompt_id=p.prompt_id AND v.version=p.active_version "
                "WHERE p.prompt_id=%s AND p.status='active' AND v.status='active'",
                (prompt_id,),
            ).fetchone()
        if not row:
            return None
        payload = json.loads(row["record_json"])
        payload.update({
            "prompt_id": row["prompt_id"], "source_id": row["source_id"],
            "external_id": row["external_id"], "active_version": int(row["active_version"]),
            "title": row["title"], "category": row["category"], "category_id": row["category_id"],
            "body": row["body"], "content_sha256": row["content_sha256"], "status": "active",
        })
        return payload

    def list_active_prompts(self, query: str = "", category_id: str | None = None,
                            limit: int = 50, offset: int = 0):
        bounded = self._bounded(limit, 200)
        skip = max(0, min(int(offset), 100000))
        needle = str(query or "").strip().lower()
        clauses = ["p.status='active'", "v.status='active'"]
        params: list[Any] = []
        if category_id:
            clauses.append("p.category_id=%s")
            params.append(category_id)
        if needle:
            clauses.append("(LOWER(p.title) LIKE %s OR LOWER(p.category) LIKE %s)")
            params.extend([f"%{needle}%", f"%{needle}%"])
        where = " AND ".join(clauses)
        with self._session() as connection:
            count = connection.execute(
                "SELECT COUNT(*) AS n FROM prompts p JOIN prompt_versions v ON v.prompt_id=p.prompt_id AND v.version=p.active_version WHERE " + where,
                tuple(params),
            ).fetchone()["n"]
            rows = connection.execute(
                "SELECT p.*,v.record_json,v.content_sha256 FROM prompts p "
                "JOIN prompt_versions v ON v.prompt_id=p.prompt_id AND v.version=p.active_version "
                "WHERE " + where + " ORDER BY p.category_id,p.prompt_id LIMIT %s OFFSET %s",
                tuple(params + [bounded, skip]),
            ).fetchall()
        items = []
        for row in rows:
            payload = json.loads(row["record_json"])
            payload.update({
                "prompt_id": row["prompt_id"], "source_id": row["source_id"],
                "external_id": row["external_id"], "active_version": int(row["active_version"]),
                "title": row["title"], "category": row["category"], "category_id": row["category_id"],
                "content_sha256": row["content_sha256"], "status": "active",
            })
            payload.pop("body", None)
            items.append(payload)
        return items, int(count)

    def list_active_prompt_categories(self):
        with self._session() as connection:
            rows = connection.execute(
                "SELECT p.category_id,p.category,COUNT(*) AS count FROM prompts p "
                "JOIN prompt_versions v ON v.prompt_id=p.prompt_id AND v.version=p.active_version "
                "WHERE p.status='active' AND v.status='active' "
                "GROUP BY p.category_id,p.category ORDER BY p.category"
            ).fetchall()
        return [{"id": row["category_id"], "name": row["category"], "count": int(row["count"])} for row in rows]

    def list_prompt_versions(self, statuses: tuple[str, ...] = ("staged",), limit: int = 100):
        bounded = self._bounded(limit, 200)
        values = tuple(statuses)
        if not values:
            return []
        marks = ",".join(["%s"] * len(values))
        with self._session() as connection:
            rows = connection.execute(
                "SELECT v.record_json FROM prompt_versions v WHERE v.status IN (" + marks + ") "
                "ORDER BY v.created_at DESC,v.prompt_id LIMIT %s",
                values + (bounded,),
            ).fetchall()
        return [json.loads(row["record_json"]) for row in rows]

    def seed_prompt_catalog(self, source: dict[str, Any], rows: list[dict[str, Any]]) -> int:
        inserted = 0
        now = time.time()
        with self._session() as connection:
            connection.execute(
                "INSERT INTO prompt_sources(source_id,status,record_json,created_at,updated_at) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(source_id) DO NOTHING",
                (source["source_id"], source["status"], self._dump(source), now, now),
            )
            for record in rows:
                existing = connection.execute(
                    "SELECT prompt_id FROM prompts WHERE prompt_id=%s", (record["prompt_id"],)
                ).fetchone()
                if existing:
                    same = connection.execute(
                        "SELECT content_sha256 FROM prompt_versions WHERE prompt_id=%s AND version=1",
                        (record["prompt_id"],),
                    ).fetchone()
                    if not same or same["content_sha256"] != record["content_sha256"]:
                        raise ValueError("Seed prompt ID already exists with different version content.")
                    continue
                connection.execute(
                    "INSERT INTO prompts(prompt_id,source_id,external_id,title,category,category_id,status,active_version,candidate_version,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s,%s,1,NULL,%s,%s)",
                    (record["prompt_id"], source["source_id"], record["external_id"],
                     record["title"], record["category"], record["category_id"],
                     "active", now, now),
                )
                payload = dict(record)
                payload.update({"version": 1, "status": "active"})
                connection.execute(
                    "INSERT INTO prompt_versions(prompt_id,version,status,content_sha256,body,record_json,created_at,reviewed_at) VALUES(%s,1,'active',%s,NULL,%s,%s,%s)",
                    (record["prompt_id"], record["content_sha256"], self._dump(payload), now, now),
                )
                inserted += 1
        return inserted

    def list_tasks(self, limit: int = 100):
        with self._session() as connection:
            rows = connection.execute(
                "SELECT task_id,agent_id,status,payload_json,result_json,created_at,updated_at "
                "FROM tasks ORDER BY created_at DESC LIMIT %s",
                (self._bounded(limit, 200),),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            payload = json.loads(item.pop("payload_json") or "{}")
            item["objective"] = payload.get("objective", "")
            item["inputs"] = payload.get("inputs", {})
            item["source_refs"] = payload.get("source_refs", [])
            item["provider_route"] = payload.get("provider_route")
            item["requested_skill_ids"] = payload.get("requested_skill_ids", [])
            item["parent_task_id"] = payload.get("parent_task_id")
            item["result"] = json.loads(item.pop("result_json")) if item.get("result_json") else None
            items.append(item)
        return items
