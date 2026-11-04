from __future__ import annotations

from typing import Any
import hashlib
import json
import math
import secrets
import time
import uuid


class MediaJobError(RuntimeError):
    """Base error for media-job lifecycle operations."""


class MediaJobConflict(MediaJobError):
    """An idempotency key was reused for a different request."""


class MediaJobService:
    """Media-job repository and state machine over the existing StateStore.

    The service uses the StateStore's existing transaction/session boundary;
    it never opens a second database. SQLite creates its local-development
    table lazily. PostgreSQL requires the additive migration 003 to be applied.
    """

    STATES = frozenset({
        "queued", "claimed", "inspecting", "rendering", "post_render_qa",
        "ready_for_human_review", "failed", "qa_blocked",
        "cancel_requested", "cancelled",
    })
    TERMINAL = frozenset({"ready_for_human_review", "failed", "qa_blocked", "cancelled"})
    TRANSITIONS = {
        "queued": {"cancelled", "failed"},
        "claimed": {"inspecting", "cancel_requested", "failed"},
        "inspecting": {"rendering", "cancel_requested", "failed", "qa_blocked"},
        "rendering": {"post_render_qa", "cancel_requested", "failed", "qa_blocked"},
        "post_render_qa": {"ready_for_human_review", "cancel_requested", "failed", "qa_blocked"},
        "cancel_requested": {"cancelled", "failed"},
        "ready_for_human_review": set(),
        "failed": set(),
        "qa_blocked": set(),
        "cancelled": set(),
    }

    def __init__(self, store):
        self.store = store
        self.backend = getattr(store, "backend", "sqlite")
        if self.backend == "sqlite":
            with self.store._session() as connection:
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS media_jobs (
                        job_id TEXT PRIMARY KEY,
                        task_id TEXT NOT NULL,
                        idempotency_key TEXT NOT NULL,
                        request_sha256 TEXT NOT NULL,
                        request_json TEXT NOT NULL,
                        state TEXT NOT NULL,
                        attempt_count INTEGER NOT NULL DEFAULT 0,
                        lease_owner TEXT,
                        lease_token TEXT,
                        lease_expires_at REAL,
                        cancel_requested INTEGER NOT NULL DEFAULT 0,
                        result_json TEXT,
                        created_at REAL NOT NULL,
                        updated_at REAL NOT NULL,
                        UNIQUE(task_id, idempotency_key)
                    )
                """)
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_media_jobs_state_created "
                    "ON media_jobs(state, created_at)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_media_jobs_lease "
                    "ON media_jobs(state, lease_expires_at)"
                )
        elif self.backend == "postgres":
            try:
                with self.store._session() as connection:
                    connection.execute("SELECT job_id FROM media_jobs LIMIT 0")
            except Exception as exc:
                raise MediaJobError(
                    f"PostgreSQL media-job migration 003 is not available ({type(exc).__name__})."
                ) from None
        else:
            raise MediaJobError("Unsupported StateStore backend.")

    def _placeholder(self) -> str:
        return "%s" if self.backend == "postgres" else "?"

    @staticmethod
    def _dump(value: Any) -> str:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        )

    @staticmethod
    def _decode(row) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        item["cancel_requested"] = bool(item.get("cancel_requested"))
        return item

    def _event(self, connection, event_type: str, job: dict[str, Any], **extra) -> None:
        now = time.time()
        payload = {
            "job_id": job["job_id"],
            "task_id": job["task_id"],
            "state": job["state"],
            "attempt_count": job["attempt_count"],
            "request_sha256": job["request_sha256"],
            **extra,
        }
        marker = self._placeholder()
        connection.execute(
            f"INSERT INTO events(ts,task_id,agent_id,event_type,payload_json) "
            f"VALUES({marker},{marker},{marker},{marker},{marker})",
            (now, job["task_id"], None, event_type, self._dump(payload)),
        )

    def _get_in(self, connection, job_id: str):
        marker = self._placeholder()
        return connection.execute(
            f"SELECT * FROM media_jobs WHERE job_id={marker}", (job_id,)
        ).fetchone()

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self.store._session() as connection:
            row = self._get_in(connection, job_id)
        return self._decode(row)

    def _get_by_key(self, task_id: str, idempotency_key: str):
        marker = self._placeholder()
        with self.store._session() as connection:
            row = connection.execute(
                f"SELECT * FROM media_jobs WHERE task_id={marker} AND idempotency_key={marker}",
                (task_id, idempotency_key),
            ).fetchone()
        return self._decode(row)

    def create(
        self, *, task_id: str, idempotency_key: str,
        request: dict[str, Any], job_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-empty string.")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("idempotency_key must be a non-empty string.")
        if not isinstance(request, dict):
            raise ValueError("request must be a JSON object.")
        request_json = self._dump(request)
        request_sha256 = hashlib.sha256(request_json.encode("utf-8")).hexdigest()
        now = time.time()
        record = {
            "job_id": job_id or str(uuid.uuid4()),
            "task_id": task_id,
            "idempotency_key": idempotency_key,
            "request_sha256": request_sha256,
            "request_json": request_json,
            "state": "queued",
            "attempt_count": 0,
            "lease_owner": None,
            "lease_token": None,
            "lease_expires_at": None,
            "cancel_requested": False,
            "result_json": None,
            "created_at": now,
            "updated_at": now,
        }
        marker = self._placeholder()
        try:
            with self.store._session() as connection:
                columns = (
                    "job_id,task_id,idempotency_key,request_sha256,request_json,state,"
                    "attempt_count,lease_owner,lease_token,lease_expires_at,cancel_requested,"
                    "result_json,created_at,updated_at"
                )
                values = ",".join([marker] * 14)
                connection.execute(
                    f"INSERT INTO media_jobs({columns}) VALUES({values})",
                    (
                        record["job_id"], task_id, idempotency_key, request_sha256,
                        request_json, "queued", 0, None, None, None, False,
                        None, now, now,
                    ),
                )
                self._event(connection, "media_job_queued", record)
            return {**record, "replayed": False}
        except Exception:
            existing = self._get_by_key(task_id, idempotency_key)
            if existing is None:
                raise
            if existing["request_sha256"] != request_sha256:
                raise MediaJobConflict(
                    "Idempotency key reused for a different media-job request."
                ) from None
            return {**existing, "replayed": True}

    def list(self, limit: int = 100, state: str | None = None) -> list[dict[str, Any]]:
        try:
            bounded = max(1, min(int(limit), 200))
        except (TypeError, ValueError, OverflowError):
            raise ValueError("limit must be an integer.") from None
        if state is not None and state not in self.STATES:
            raise ValueError("Unknown media-job state.")
        marker = self._placeholder()
        with self.store._session() as connection:
            if state is None:
                rows = connection.execute(
                    f"SELECT * FROM media_jobs ORDER BY created_at DESC LIMIT {marker}",
                    (bounded,),
                ).fetchall()
            else:
                rows = connection.execute(
                    f"SELECT * FROM media_jobs WHERE state={marker} "
                    f"ORDER BY created_at DESC LIMIT {marker}",
                    (state, bounded),
                ).fetchall()
        return [self._decode(row) for row in rows]

    def claim_one(self, worker_id: str, lease_seconds: float = 120.0) -> dict[str, Any] | None:
        if not isinstance(worker_id, str) or not worker_id.strip():
            raise ValueError("worker_id must be a non-empty string.")
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, (int, float)):
            raise ValueError("lease_seconds must be finite and positive.")
        duration = float(lease_seconds)
        if not math.isfinite(duration) or duration <= 0 or duration > 3600:
            raise ValueError("lease_seconds must be >0 and <=3600.")
        now = time.time()
        token = secrets.token_urlsafe(32)
        marker = self._placeholder()
        with self.store._session() as connection:
            if self.backend == "sqlite":
                connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                f"SELECT * FROM media_jobs WHERE state={marker} "
                f"ORDER BY created_at,job_id LIMIT 1" +
                (" FOR UPDATE SKIP LOCKED" if self.backend == "postgres" else ""),
                ("queued",),
            ).fetchone()
            if row is None:
                return None
            job_id = row["job_id"]
            cursor = connection.execute(
                f"UPDATE media_jobs SET state={marker},attempt_count=attempt_count+1,"
                f"lease_owner={marker},lease_token={marker},lease_expires_at={marker},"
                f"updated_at={marker} WHERE job_id={marker} AND state={marker}",
                ("claimed", worker_id, token, now + duration, now, job_id, "queued"),
            )
            if cursor.rowcount != 1:
                return None
            updated = self._get_in(connection, job_id)
            result = self._decode(updated)
            self._event(connection, "media_job_claimed", result, worker_id=worker_id)
            return result

    def advance(
        self, job_id: str, *, expected_state: str, target_state: str,
        worker_id: str | None, lease_token: str | None,
        result: dict[str, Any] | None = None,
    ) -> bool:
        if expected_state not in self.STATES or target_state not in self.STATES:
            raise ValueError("Unknown media-job state.")
        if target_state not in self.TRANSITIONS[expected_state]:
            raise ValueError(f"Invalid media-job transition: {expected_state} -> {target_state}.")
        if not worker_id or not lease_token:
            raise ValueError("Worker transitions require worker_id and lease_token.")
        result_json = self._dump(result) if result is not None else None
        marker = self._placeholder()
        now = time.time()
        with self.store._session() as connection:
            cursor = connection.execute(
                f"UPDATE media_jobs SET state={marker},result_json=COALESCE({marker},result_json),"
                f"updated_at={marker} WHERE job_id={marker} AND state={marker} "
                f"AND lease_owner={marker} AND lease_token={marker}",
                (target_state, result_json, now, job_id, expected_state, worker_id, lease_token),
            )
            if cursor.rowcount != 1:
                return False
            row = self._get_in(connection, job_id)
            job = self._decode(row)
            self._event(connection, "media_job_state_changed", job, from_state=expected_state, to_state=target_state)
            return True

    def cancel(self, job_id: str) -> str | None:
        marker = self._placeholder()
        now = time.time()
        with self.store._session() as connection:
            row = self._get_in(connection, job_id)
            if row is None:
                return None
            current = row["state"]
            if current in self.TERMINAL:
                return current
            target = "cancelled" if current == "queued" else "cancel_requested"
            cursor = connection.execute(
                f"UPDATE media_jobs SET state={marker},cancel_requested={marker},updated_at={marker} "
                f"WHERE job_id={marker} AND state={marker}",
                (target, True, now, job_id, current),
            )
            if cursor.rowcount != 1:
                row = self._get_in(connection, job_id)
                return row["state"] if row else None
            updated = self._decode(self._get_in(connection, job_id))
            self._event(connection, "media_job_cancel_requested" if target == "cancel_requested" else "media_job_cancelled", updated)
            return target

    def recover_expired(
        self, job_id: str, *, old_lease_token: str, worker_id: str,
        lease_seconds: float = 120.0, recovery_action: str = "retry",
    ) -> dict[str, Any] | None:
        if recovery_action != "retry":
            raise ValueError("Only a verified stopped-worker retry is supported by this operation.")
        if not old_lease_token or not worker_id:
            raise ValueError("A prior lease token and recovery worker ID are required.")
        duration = float(lease_seconds)
        if not math.isfinite(duration) or duration <= 0 or duration > 3600:
            raise ValueError("lease_seconds must be >0 and <=3600.")
        marker = self._placeholder()
        now = time.time()
        with self.store._session() as connection:
            row = self._get_in(connection, job_id)
            if row is None:
                return None
            if row["state"] not in {"claimed", "inspecting", "rendering", "post_render_qa"}:
                return None
            if row["lease_token"] != old_lease_token or row["lease_expires_at"] is None:
                return None
            if float(row["lease_expires_at"]) > now:
                return None
            # The caller must terminate and confirm the prior process tree stopped
            # before invoking retry recovery. Rotating/clearing this token fences it.
            cursor = connection.execute(
                f"UPDATE media_jobs SET state={marker},lease_owner=NULL,lease_token=NULL,"
                f"lease_expires_at=NULL,cancel_requested={marker},updated_at={marker} "
                f"WHERE job_id={marker} AND lease_token={marker} AND lease_expires_at<={marker}",
                ("queued", False, now, job_id, old_lease_token, now),
            )
            if cursor.rowcount != 1:
                return None
            updated = self._decode(self._get_in(connection, job_id))
            self._event(connection, "media_job_lease_recovered", updated, recovered_by=worker_id)
            return updated
