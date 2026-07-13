"""JSON-file store: one file per session under <state_dir>/banks/.

Zero config, and each file is self-contained (task + bank + timestamp), so listing
sessions is just a directory glob. Writes are atomic (temp file + os.replace).
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from ..schemas import MemoryBank
from .base import SessionInfo


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _safe_name(session_id: str) -> str:
    # Session id becomes a filename, so keep it to portable characters.
    return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in session_id)


class JsonFileStore:
    def __init__(self, state_dir: str | Path = ".agentmem") -> None:
        self._dir = Path(state_dir) / "banks"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self._dir / f"{_safe_name(session_id)}.json"

    def load_bank(self, session_id: str) -> MemoryBank | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        envelope = json.loads(path.read_text(encoding="utf-8"))
        return MemoryBank.model_validate(envelope["bank"])

    def save_bank(self, session_id: str, task: str, bank: MemoryBank) -> None:
        envelope = {
            "session_id": session_id,
            "task": task,
            "updated_at": _now_iso(),
            "bank": bank.model_dump(mode="json"),
        }
        path = self._path(session_id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(envelope, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

    def list_sessions(self) -> list[SessionInfo]:
        sessions: list[SessionInfo] = []
        for path in self._dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                sessions.append(
                    SessionInfo(
                        session_id=data["session_id"],
                        task=data.get("task", ""),
                        updated_at=data.get("updated_at", ""),
                    )
                )
            except (json.JSONDecodeError, KeyError):
                continue  # skip a corrupt or half-written file
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions

    def close(self) -> None:
        pass
