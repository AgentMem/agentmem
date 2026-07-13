"""The storage contract.

A store persists memory banks by session id and can list the sessions it knows
about. That's what makes cross-session memory work: a new run loads the bank the
last run left behind.

Synchronous by design: the memory-step worker runs on a background thread, so a sync
store (the SQLite backend uses the stdlib sqlite3, no extra dependency) is the
simpler fit and never blocks the action agent.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from ..schemas import MemoryBank


class SessionInfo(BaseModel):
    session_id: str
    task: str
    updated_at: str  # ISO-8601


@runtime_checkable
class Store(Protocol):
    """Persist and retrieve memory banks by session id.

    Implementations must be safe to call from a single background thread. Sessions
    are single-writer, so cross-process writes to the same session aren't a concern.
    """

    def load_bank(self, session_id: str) -> MemoryBank | None:
        """The stored bank, or None if this session has none yet."""
        ...

    def save_bank(self, session_id: str, task: str, bank: MemoryBank) -> None:
        """Persist the bank and touch the session's updated_at."""
        ...

    def list_sessions(self) -> list[SessionInfo]:
        """Every session the store knows about, newest first."""
        ...

    def close(self) -> None:
        """Flush and release handles. Safe to call more than once."""
        ...
