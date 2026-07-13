"""Eval-harness test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
from agentmem_evals.task import Task, load_task

_TASKS = Path(__file__).resolve().parents[1] / "longdebug_mini" / "tasks"


@pytest.fixture
def tasks_dir() -> Path:
    return _TASKS


@pytest.fixture
def ttl_task() -> Task:
    return load_task(_TASKS / "ttl_bug")


@pytest.fixture
def off_task() -> Task:
    return load_task(_TASKS / "off_by_one")
