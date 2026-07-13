"""Smoke test for the offline demo.

If this breaks, `agentmem demo` (the first thing a new user runs) is broken.
"""

from __future__ import annotations

from agentmem._demo import run_demo


def test_offline_demo_runs_and_intervenes(capsys) -> None:  # noqa: ANN001
    assert run_demo(live=False) == 0
    out = capsys.readouterr().out
    assert "AgentMem reminds the agent" in out  # the intervention actually fired
    assert "P-001" in out
