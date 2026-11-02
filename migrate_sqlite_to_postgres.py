from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

TABLES = (
    "tasks", "events", "agent_memory", "shared_knowledge", "idempotency",
    "outcomes", "proposals", "agent_versions", "baselines", "capabilities",
    "consumed_approvals", "workspace_devices", "workspace_records",
)
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _digest(rows: list[tuple[Any, ...]]) -> str:
    encoded = json.dumps(rows, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def migrate(source_path: Path, database_url: str) -> dict[str, Any]:
    if not source_path.is_file():
        raise FileNotFoundError("Source SQLite database file was not found.")
    if not database_url.startswith(("postgres://", "postgresql://")):
        raise ValueError("UNEXPECTED_DATABASE_URL must contain a PostgreSQL URL.")

    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("PostgreSQL migration requires the pinned psycopg runtime dependency.") from exc

    source = sqlite3.connect(f"file:{source_path.resolve()}?mode=ro", uri=True)
    source.row_factory = sqlite3.Row
    report: dict[str, Any] = {
        "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "tables": {},
        "status": "running",
    }
    try:
        existing_tables = {
            row["name"] for row in source.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        selected = [name for name in TABLES if name in existing_tables]
        if not selected:
            raise ValueError("Source SQLite file contains no recognized uneXpected runtime tables.")

        with psycopg.connect(database_url, connect_timeout=8) as target:
            target.execute("SET statement_timeout = '60000ms'")
            # Refuse a merge. A migration only runs into an empty target so no
            # existing PostgreSQL record can be silently overwritten/skipped.
            for table in selected:
                count = target.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                if count:
                    raise RuntimeError(f"Target table {table} is not empty; migration aborted without writes.")

            for table in selected:
                info = source.execute(f'PRAGMA table_info("{table}")').fetchall()
                columns = [row["name"] for row in info]
                if not columns or any(not IDENTIFIER.fullmatch(column) for column in columns):
                    raise ValueError(f"Source table {table} has an unsupported column definition.")
                primary_key = [row["name"] for row in sorted(info, key=lambda item: item["pk"]) if row["pk"]]
                order = primary_key or columns
                select_sql = f'SELECT {", ".join(chr(34)+column+chr(34) for column in columns)} FROM "{table}" ORDER BY {", ".join(chr(34)+column+chr(34) for column in order)}'
                rows = source.execute(select_sql).fetchall()
                values = [tuple(row[column] for column in columns) for row in rows]
                columns_sql = ", ".join(f'"{column}"' for column in columns)
                placeholders = ", ".join(["%s"] * len(columns))
                insert_sql = f'INSERT INTO "{table}" ({columns_sql}) VALUES ({placeholders})'
                for offset in range(0, len(values), 250):
                    target.executemany(insert_sql, values[offset:offset + 250])

                source_hash = _digest(values)
                imported = target.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                if imported != len(values):
                    raise RuntimeError(f"Row-count verification failed for table {table}.")
                order_sql = ", ".join('"' + column + '"' for column in order)
                target_rows = target.execute(
                    f'SELECT {columns_sql} FROM "{table}" ORDER BY {order_sql}'
                ).fetchall()
                target_values = [tuple(row[column] if isinstance(row, dict) else row[index]
                                       for index, column in enumerate(columns)) for row in target_rows]
                target_hash = _digest(target_values)
                if target_hash != source_hash:
                    raise RuntimeError(f"Content verification failed for table {table}.")
                report["tables"][table] = {
                    "rows": len(values),
                    "sha256": source_hash,
                    "verified": True,
                }

            if "events" in selected:
                target.execute(
                    "SELECT setval(pg_get_serial_sequence('events','event_id'), "
                    "COALESCE((SELECT MAX(event_id) FROM events),1), "
                    "EXISTS(SELECT 1 FROM events))"
                )
            target.commit()
        report["status"] = "verified"
        return report
    except Exception:
        report["status"] = "failed"
        raise
    finally:
        source.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy an uneXpected SQLite state backup to an empty PostgreSQL database.")
    parser.add_argument("--source-db", required=True, type=Path, help="Path to a verified SQLite backup file.")
    args = parser.parse_args()
    database_url = os.getenv("UNEXPECTED_DATABASE_URL", "").strip()
    try:
        result = migrate(args.source_db, database_url)
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": type(exc).__name__ + ": " + str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
