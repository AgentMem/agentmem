"""SQLite store: many sessions in one file."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from ..schemas import MemoryBank
from .base import SessionInfo

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id  TEXT PRIMARY KEY,
    task        TEXT NOT NULL DEFAULT '',
    bank        TEXT NOT NULL,          -- MemoryBank serialized as JSON
    updated_at  TEXT NOT NULL
);
"""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class SqliteStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: the worker thread owns the connection, not the
        # thread that built it. Still only ever touched from one thread at a time.
        self._db = sqlite3.connect(self._path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)
        self._db.commit()

    def load_bank(self, session_id: str) -> MemoryBank | None:
        row = self._db.execute(
            "SELECT bank FROM sessions WHERE session_id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        return MemoryBank.model_validate_json(row[0])

    def save_bank(self, session_id: str, task: str, bank: MemoryBank) -> None:
        # Upsert: keep the original task, always refresh the bank.
        self._db.execute(
            """
            INSERT INTO sessions (session_id, task, bank, updated_at)
            VALUES (:sid, :task, :bank, :ts)
            ON CONFLICT(session_id) DO UPDATE SET bank = :bank, updated_at = :ts
            """,
            {
                "sid": session_id,
                "task": task,
                "bank": bank.model_dump_json(),
                "ts": _now_iso(),
            },
        )
        self._db.commit()

    def list_sessions(self) -> list[SessionInfo]:
        rows = self._db.execute(
            "SELECT session_id, task, updated_at FROM sessions ORDER BY updated_at DESC"
        ).fetchall()
        return [SessionInfo(session_id=r[0], task=r[1], updated_at=r[2]) for r in rows]

    def close(self) -> None:
        self._db.close()
