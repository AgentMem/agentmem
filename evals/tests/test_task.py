"""Task loading."""

from __future__ import annotations

from pathlib import Path

from agentmem_evals.task import Task, discover_tasks


def test_load_ttl_task(ttl_task: Task) -> None:
    assert ttl_task.id == "ttl_bug"
    assert ttl_task.sessions == 2
    assert ttl_task.repo_dir.is_dir()
    assert ttl_task.verify_dir.is_dir()

    assert ttl_task.forbidden_patterns[0].file == "api.py"
    assert ttl_task.offline is not None
    assert ttl_task.offline.recognize == "config.py"


def test_discover_tasks_sorted(tasks_dir: Path) -> None:
    ids = [t.id for t in discover_tasks(tasks_dir)]
    assert ids == ["off_by_one", "ttl_bug"]
