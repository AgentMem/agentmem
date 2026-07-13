"""Where past decisions live: one row per memory-step, its state, what we did, and how
it turned out.

The return (G) isn't known until the session ends and the evaluator scores it, so a
row is written "pending" (G null) at decision time and filled in at SessionEnd. Only
finalized rows feed the advantage estimate, a decision we can't yet grade shouldn't
influence the next one.

Its own SQLite file (.agentmem/policy.db), separate from the bank, so it can grow
without bloating the thing we load every step.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

InjectClass = Literal["requirement", "env", "repeat_fail", "diagnosis", "subgoal", "state_change"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS decisions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    step         INTEGER NOT NULL,
    state_sig    TEXT NOT NULL,          -- JSON array of tokens
    action       TEXT NOT NULL,          -- silent | inject
    inject_class TEXT,
    model        TEXT NOT NULL DEFAULT '',
    g            REAL                     -- NULL until finalized at SessionEnd
);
"""


class DecisionRecord(BaseModel):
    state_sig: list[str]
    action: Literal["silent", "inject"]
    inject_class: InjectClass | None = None
    g: float = 0.0
    session_id: str = ""
    step: int = 0
    model: str = ""


class PolicyStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self._path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)
        self._db.commit()

    def record(
        self,
        *,
        session_id: str,
        step: int,
        state_sig: list[str],
        action: str,
        inject_class: str | None,
        model: str,
    ) -> None:
        """Write a pending decision (return unknown until the session ends)."""
        self._db.execute(
            "INSERT INTO decisions (session_id, step, state_sig, action, inject_class, model, g) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL)",
            (session_id, step, json.dumps(state_sig), action, inject_class, model),
        )
        self._db.commit()

    def finalize(self, session_id: str, returns: dict[int, float]) -> None:
        """Fill in G for a session's steps once the evaluator has scored them."""
        self._db.executemany(
            "UPDATE decisions SET g = ? WHERE session_id = ? AND step = ?",
            [(g, session_id, step) for step, g in returns.items()],
        )
        self._db.commit()

    def finalized(self) -> list[DecisionRecord]:
        """Every graded decision, the memory the advantage estimate draws on."""
        rows = self._db.execute(
            "SELECT state_sig, action, inject_class, g, session_id, step, model "
            "FROM decisions WHERE g IS NOT NULL"
        ).fetchall()
        return [
            DecisionRecord(
                state_sig=json.loads(r[0]),
                action=r[1],
                inject_class=r[2],
                g=r[3],
                session_id=r[4],
                step=r[5],
                model=r[6],
            )
            for r in rows
        ]

    def count(self) -> int:
        row = self._db.execute("SELECT COUNT(*) FROM decisions WHERE g IS NOT NULL").fetchone()
        return int(row[0])

    def close(self) -> None:
        self._db.close()
