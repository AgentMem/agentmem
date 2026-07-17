"""Chain many contributors' receipts into one tamper-evident team timeline, idempotent by
receipt id and serialized under a lock."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from agentmem.verify import ActionReceipt
from pydantic import BaseModel


class TeamEntry(BaseModel):
    """One receipt as the team recorded it: who pushed it, when, and its link in the chain."""

    receipt: ActionReceipt
    contributor: str
    received_at: str
    prev_hash: str
    hash: str

    def compute_hash(self) -> str:
        payload = json.dumps(
            {
                "receipt_hash": self.receipt.hash,
                "contributor": self.contributor,
                "received_at": self.received_at,
                "prev_hash": self.prev_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()


def _slug(team: str) -> str:
    safe = "".join(c if (c.isalnum() or c in "-_") else "-" for c in team).strip("-")
    return safe[:64] or "team"


class TeamLedger:
    """Per-team, append-only storage for the hosted feed."""

    def __init__(self, base: Path | str) -> None:
        self.base = Path(base)

    def _dir(self, team: str) -> Path:
        return self.base / _slug(team)

    def _path(self, team: str) -> Path:
        return self._dir(team) / "team.jsonl"

    @contextmanager
    def _locked(self, team: str) -> Iterator[None]:
        directory = self._dir(team)
        directory.mkdir(parents=True, exist_ok=True)
        try:
            import fcntl
        except ImportError:
            yield
            return
        with (directory / ".lock").open("w") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _raw(self, team: str) -> list[dict]:
        path = self._path(team)
        if not path.exists():
            return []
        return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]

    def head_hash(self, team: str) -> str:
        rows = self._raw(team)
        return str(rows[-1]["hash"]) if rows else ""

    def has(self, team: str, receipt_id: str) -> bool:
        return any(r["receipt"]["receipt_id"] == receipt_id for r in self._raw(team))

    def append(self, team: str, receipt: ActionReceipt, contributor: str) -> TeamEntry | None:
        """Chain a receipt onto the team's timeline. Idempotent by receipt id (returns None
        if it is already there). Rejects a receipt whose own facts do not hash to its seal."""
        if receipt.tampered():
            raise ValueError("receipt seal does not match its contents")
        with self._locked(team):
            if self.has(team, receipt.receipt_id):
                return None
            entry = TeamEntry(
                receipt=receipt,
                contributor=contributor,
                received_at=datetime.now(UTC).isoformat(timespec="seconds"),
                prev_hash=self.head_hash(team),
                hash="",
            )
            entry.hash = entry.compute_hash()
            with self._path(team).open("a") as handle:
                handle.write(entry.model_dump_json() + "\n")
            return entry

    def entries(
        self,
        team: str,
        *,
        actor: str | None = None,
        verdict: str | None = None,
        contributor: str | None = None,
        limit: int | None = None,
    ) -> list[TeamEntry]:
        """Matching entries, newest first."""
        out: list[TeamEntry] = []
        for row in reversed(self._raw(team)):
            entry = TeamEntry.model_validate(row)
            if actor and entry.receipt.actor != actor:
                continue
            if verdict and entry.receipt.verdict != verdict:
                continue
            if contributor and entry.contributor != contributor:
                continue
            out.append(entry)
            if limit and len(out) >= limit:
                break
        return out

    def summary(self, team: str) -> dict:
        entries = [TeamEntry.model_validate(r) for r in self._raw(team)]
        faithful = sum(1 for e in entries if e.receipt.verdict == "FAITHFUL")
        return {
            "total": len(entries),
            "faithful": faithful,
            "flagged": len(entries) - faithful,
            "contributors": sorted({e.contributor for e in entries}),
            "actors": sorted({e.receipt.actor for e in entries}),
        }

    def verify(self, team: str) -> list[str]:
        """Report any break: a receipt edited after sealing, a team entry edited, or a link
        whose prev_hash does not point at the entry before it."""
        problems: list[str] = []
        prev = ""
        for row in self._raw(team):
            entry = TeamEntry.model_validate(row)
            rid = entry.receipt.receipt_id
            if entry.receipt.tampered():
                problems.append(f"{rid}: receipt edited after sealing")
            if entry.hash != entry.compute_hash():
                problems.append(f"{rid}: team entry edited after sealing")
            if entry.prev_hash != prev:
                problems.append(f"{rid}: team chain broken")
            prev = entry.hash
        return problems
