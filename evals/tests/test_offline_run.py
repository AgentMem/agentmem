"""End-to-end offline runs: real temp repo, real pytest, scripted agent + memory."""

from __future__ import annotations

from agentmem_evals.runner import run_task
from agentmem_evals.task import Task


def test_baseline_flails_and_violates(ttl_task: Task) -> None:
    r = run_task(ttl_task, "baseline", seed=0, offline=True)
    assert r.passed is False
    assert r.requirement_violations >= 1  # kept editing the public API
    assert r.interventions == 0
    assert r.repeated_failures >= 2  # ran the same failing tests over and over


def test_agentmem_recovers_cleanly(ttl_task: Task) -> None:
    r = run_task(ttl_task, "agentmem", seed=0, offline=True)
    assert r.passed is True
    assert (
        r.requirement_violations == 0
    )  # reminder redirected it, and the fix reverted the bad edit
    assert r.interventions >= 1
    assert r.repeated_failures < 5  # far less flailing than baseline


def test_off_by_one_contrast(off_task: Task) -> None:
    assert run_task(off_task, "baseline", seed=0, offline=True).passed is False
    assert run_task(off_task, "agentmem", seed=0, offline=True).passed is True


def test_agentmem_is_more_selective_than_full_bank(ttl_task: Task) -> None:
    # Same outcome, far fewer interruptions: the whole point of intervening selectively.
    selective = run_task(ttl_task, "agentmem", seed=0, offline=True)
    full_bank = run_task(ttl_task, "full_bank", seed=0, offline=True)
    assert selective.passed and full_bank.passed
    assert selective.interventions < full_bank.interventions
