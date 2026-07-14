"""Load a task from disk."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ForbiddenPattern:
    file: str
    pattern: str
    message: str


@dataclass(frozen=True)
class OfflineScript:
    """Everything the offline harness needs to run a task with no model.

    `memory_hint` is the diagnosis a scripted memory agent "reaches" after repeated
    failures; `recognize` is the substring the scripted action agent watches for in a
    reminder before it applies `fix_command` instead of the wrong `attempt_command`.
    Real (model-driven) runs ignore all of this.
    """

    memory_hint: str
    recognize: str
    fix_command: str
    attempt_command: str


@dataclass(frozen=True)
class Task:
    id: str
    description: str
    root: Path
    requirements: list[str] = field(default_factory=list)
    forbidden_patterns: list[ForbiddenPattern] = field(default_factory=list)
    sessions: int = 3
    max_turns: int = 15
    repo_test_command: str = "python -m pytest tests -q"
    verify_command: str = "python -m pytest _verify -q"
    offline: OfflineScript | None = None

    @property
    def repo_dir(self) -> Path:
        return self.root / "repo"

    @property
    def verify_dir(self) -> Path:
        return self.root / "verify"


def load_task(path: str | Path) -> Task:
    root = Path(path)
    data = tomllib.loads((root / "task.toml").read_text(encoding="utf-8"))

    patterns = [
        ForbiddenPattern(
            file=p["file"], pattern=p["pattern"], message=p.get("message", p["pattern"])
        )
        for p in data.get("forbidden_patterns", [])
    ]

    offline = None
    if "offline" in data:
        o = data["offline"]
        offline = OfflineScript(
            memory_hint=o["memory_hint"],
            recognize=o["recognize"],
            fix_command=o["fix_command"],
            attempt_command=o["attempt_command"],
        )

    task = Task(
        id=data["id"],
        description=data["description"],
        root=root,
        requirements=list(data.get("requirements", [])),
        forbidden_patterns=patterns,
        sessions=int(data.get("sessions", 3)),
        max_turns=int(data.get("max_turns", 15)),
        repo_test_command=data.get("repo_test_command", "python -m pytest tests -q"),
        verify_command=data.get("verify_command", "python -m pytest _verify -q"),
        offline=offline,
    )
    if not task.repo_dir.is_dir():
        raise FileNotFoundError(f"Task {task.id!r} has no repo/ directory at {task.repo_dir}")
    return task


def discover_tasks(tasks_dir: str | Path) -> list[Task]:
    """Load every task under a directory (one subdir per task), sorted by id."""
    base = Path(tasks_dir)
    tasks = [load_task(p) for p in base.iterdir() if (p / "task.toml").exists()]
    return sorted(tasks, key=lambda t: t.id)
