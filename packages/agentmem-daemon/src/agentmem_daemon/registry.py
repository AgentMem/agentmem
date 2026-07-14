"""Keeps one MemorySession alive per project."""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable

from agentmem import MemorySession

# The task we start a session with before the user's first prompt tells us the real
# goal. The prompt endpoint upgrades it.
PLACEHOLDER_TASK = "(Claude Code session)"

SessionFactory = Callable[[str, str, str], MemorySession]  # (project_key, cwd, task) -> session


class SessionRegistry:
    def __init__(self, factory: SessionFactory) -> None:
        self._factory = factory
        self._sessions: dict[str, MemorySession] = {}
        self._lock = threading.Lock()

    def get_or_create(self, key: str, cwd: str, task: str = PLACEHOLDER_TASK) -> MemorySession:
        with self._lock:
            session = self._sessions.get(key)
            if session is None:
                session = self._factory(key, cwd, task)
                self._sessions[key] = session
            return session

    def get(self, key: str) -> MemorySession | None:
        with self._lock:
            return self._sessions.get(key)

    def close_all(self) -> None:
        """Persist and shut down every session. Called on daemon shutdown."""
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            # One stuck session shouldn't block shutdown of the rest.
            with contextlib.suppress(Exception):
                session.close()
