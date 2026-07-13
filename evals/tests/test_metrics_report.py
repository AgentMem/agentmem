"""Metric aggregation and report writing."""

from __future__ import annotations

import json
from pathlib import Path

from agentmem_evals.metrics import Report, TaskResult, summarize
from agentmem_evals.report import write_report


def _result(condition: str, seed: int, passed: bool) -> TaskResult:
    return TaskResult(
        task_id="t",
        condition=condition,
        seed=seed,
        passed=passed,
        repeated_failures=0,
        requirement_violations=0,
        interventions=0,
        memory_steps=0,
        memory_tokens=0,
        action_tokens=0,
        turns=0,
    )


def test_pass_rate_and_spread_across_seeds() -> None:
    results = [
        _result("agentmem", 0, True),
        _result("agentmem", 1, False),
        _result("baseline", 0, False),
        _result("baseline", 1, False),
    ]
    summary = {s.condition: s for s in summarize(results)}

    assert summary["agentmem"].pass_rate == 0.5  # 1.0 on seed 0, 0.0 on seed 1
    assert summary["agentmem"].pass_rate_std > 0
    assert summary["baseline"].pass_rate == 0.0
    assert summary["baseline"].pass_rate_std == 0.0


def test_summary_is_ordered_baseline_first() -> None:
    results = [_result("agentmem", 0, True), _result("baseline", 0, False)]
    order = [s.condition for s in summarize(results)]
    assert order.index("baseline") < order.index("agentmem")


def test_write_report(tmp_path: Path) -> None:
    results = [_result("baseline", 0, False), _result("agentmem", 0, True)]
    report = Report(results=results, summaries=summarize(results))

    out = write_report(report, tmp_path, meta={"mode": "offline", "seeds": 1, "tasks": 1})

    assert out.exists()
    text = out.read_text()
    assert "pass@1" in text
    assert "Takeaway" in text  # baseline + agentmem present -> takeaway line
    assert json.loads((tmp_path / "results.json").read_text())["summaries"]
