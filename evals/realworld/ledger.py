"""What actually happened, taken from the repo rather than from anyone's account of it.

grounding.py asks whether the things an answer names exist. This asks whether what
it says it did is what it did. The two are independent: the more-itertools memory
arm named only real files and still reported skipping a test file it had written.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Ours, not the agent's, and it would otherwise read as a file the agent created.
_IGNORE = {"Dockerfile.agentmem"}


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

    def summary(self) -> dict:
        return {
            "created": sorted(self.created),
            "modified": sorted(self.modified),
            "deleted": sorted(self.deleted),
            "commands": len(self.commands),
        }


def from_repo(repo: Path, calls: list[dict] | None = None) -> Ledger:
    """Read the ledger out of a working tree the agent has finished with.

    git is the witness: it knows what the tree looked like at the ref and what it
    looks like now, and it has no opinion about what the agent meant to do. Runs that
    kept no command log still get file claims checked, which is most of them.
    """
    led = Ledger()
    # -uall, because git otherwise collapses a wholly untracked directory to `?? tests/`
    # and the file inside it never enters the ledger. Every claim about that file would
    # then find no evidence, and a denial of having written it would come back
    # supported. The one metric this whole file exists for would flatter us by default.
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
    """Match a claimed path against a real one, tolerantly but not loosely.

    An agent writes `/work/tests/x.py` where git says `tests/x.py`, so compare from
    the right. Bare basenames are allowed because answers use them, and the cost is
    only that two files of the same name in different directories would be conflated,
    which resolves a claim as supported rather than inventing a contradiction.
    """
    want = claim_path.strip().lstrip("/").removeprefix("work/")
    for r in real:
        if r == want or r.endswith("/" + want) or Path(r).name == Path(want).name:
            return r
    return None
