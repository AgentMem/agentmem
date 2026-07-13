"""Condition wiring."""

from __future__ import annotations

from pathlib import Path

import pytest
from agentmem_evals.agent import ScriptedMemoryProvider
from agentmem_evals.conditions import CONDITIONS, Strategy, build_strategy
from agentmem_evals.task import Task


def test_conditions_list() -> None:
    assert set(CONDITIONS) == {
        "baseline",
        "agentmem",
        "full_bank",
        "always_inject",
        "injection_only",
    }


def test_baseline_has_no_memory(ttl_task: Task, tmp_path: Path) -> None:
    strategy = build_strategy("baseline", ttl_task, tmp_path)
    assert type(strategy) is Strategy
    assert strategy.context() is None
    strategy.close()


def test_session_conditions_build_a_session(ttl_task: Task, tmp_path: Path) -> None:
    for name in ("agentmem", "full_bank", "always_inject"):
        strategy = build_strategy(name, ttl_task, tmp_path / name, ScriptedMemoryProvider("hint"))
        assert strategy._session is not None
        strategy.close()


def test_unknown_condition_raises(ttl_task: Task, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown condition"):
        build_strategy("nope", ttl_task, tmp_path)
