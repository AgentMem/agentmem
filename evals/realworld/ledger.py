"""What happened, read from the repo rather than from anyone's account of it.

grounding.py asks whether the things an answer names exist. This asks whether what it
says it did is what it did, which is independent: an answer can name only real files
and still be wrong about them.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_IGNORE = {"Dockerfile.agentmem"}  # ours, not the agent's work


def _git(repo: Path, *args: str) -> str:
    p = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, errors="replace"
    )
    return p.stdout if p.returncode == 0 else ""


@dataclass
class Ledger:
    """The record a claim is checked against. Every field is observed, not inferred."""

    created: set[str] = field(default_factory=set)
    modified: set[str] = field(default_factory=set)
    deleted: set[str] = field(default_factory=set)
    commands: list[str] = field(default_factory=list)
    outputs: str = ""

    @property
    def touched(self) -> set[str]:
        return self.created | self.modified | self.deleted

    def summary(self) -> dict[str, Any]:
        return {
            "created": sorted(self.created),
            "modified": sorted(self.modified),
            "deleted": sorted(self.deleted),
            "commands": len(self.commands),
        }


def from_repo(repo: Path, calls: list[dict[str, Any]] | None = None) -> Ledger:
    """Read the ledger out of a working tree the agent has finished with.

    A run that kept no command log still gets its file claims checked.
    """
    led = Ledger()
    # -uall or git collapses an untracked directory to `?? tests/` and the file
    # inside it never enters the ledger, which reads as evidence of absence.
    for line in _git(repo, "status", "--porcelain", "-uall").splitlines():
        if len(line) < 4:
            continue
        code, path = line[:2], line[3:].strip().strip('"')
        if Path(path).name in _IGNORE:
            continue
        if code == "??":
            led.created.add(path)
        elif "D" in code:
            led.deleted.add(path)
        elif "M" in code or "A" in code or "R" in code:
            led.modified.add(path)
    for c in calls or []:
        led.commands.append(c.get("command", ""))
        led.outputs += (c.get("output", "") or "") + "\n"
    return led


def path_matches(claim_path: str, real: set[str]) -> str | None:
    """Match a claimed path against a real one, from the right.

    An agent writes `/work/tests/x.py` where git says `tests/x.py`. Same-named files in
    different directories conflate, which can only support a claim, never refute one.
    """
    want = claim_path.strip().lstrip("/").removeprefix("work/")
    for r in real:
        if r == want or r.endswith("/" + want) or Path(r).name == Path(want).name:
            return r
    return None
