"""SQLite state backend. Handles concurrent writers better than the JSON file."""

from __future__ import annotations

import sqlite3
from typing import List, Optional

from ..models import WorkerRecord
from .base import StateBackend

_COLUMNS = [
    "worker_id",
    "provider",
    "instance_id",
    "status",
    "gpu",
    "hourly_cost",
    "started_at",
    "last_heartbeat",
    "idle_since",
]


class SqliteStateBackend(StateBackend):
    def __init__(self, path: str):
        self.path = str(path)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workers (
                    worker_id      TEXT PRIMARY KEY,
                    provider       TEXT NOT NULL,
                    instance_id    TEXT,
                    status         TEXT NOT NULL,
                    gpu            TEXT,
                    hourly_cost    REAL NOT NULL DEFAULT 0,
                    started_at     REAL NOT NULL DEFAULT 0,
                    last_heartbeat REAL,
                    idle_since     REAL
                )
                """
            )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> WorkerRecord:
        return WorkerRecord.from_dict({k: row[k] for k in _COLUMNS})

    def add(self, record: WorkerRecord) -> None:
        d = record.to_dict()
        with self._conn() as conn:
            conn.execute(
                f"INSERT OR REPLACE INTO workers ({','.join(_COLUMNS)}) "
                f"VALUES ({','.join('?' for _ in _COLUMNS)})",
                [d[c] for c in _COLUMNS],
            )

    def get(self, worker_id: str) -> Optional[WorkerRecord]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM workers WHERE worker_id = ?", (worker_id,)
            ).fetchone()
            return self._row_to_record(row) if row else None

    def update(self, worker_id: str, **fields) -> None:
        self._validate_fields(fields)
        if not fields:
            return
        assignments = ", ".join(f"{k} = ?" for k in fields)  # keys are whitelisted
        values = list(fields.values()) + [worker_id]
        with self._conn() as conn:
            conn.execute(
                f"UPDATE workers SET {assignments} WHERE worker_id = ?", values
            )

    def remove(self, worker_id: str) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM workers WHERE worker_id = ?", (worker_id,))

    def all(self) -> List[WorkerRecord]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM workers").fetchall()
            return [self._row_to_record(r) for r in rows]

