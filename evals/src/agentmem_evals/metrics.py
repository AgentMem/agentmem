"""Result rows and their aggregation."""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field


@dataclass
class TaskResult:
    task_id: str
    condition: str
    seed: int
    passed: bool
    repeated_failures: int
    requirement_violations: int
    interventions: int
    memory_steps: int
    memory_tokens: int
    action_tokens: int
    turns: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ConditionSummary:
    condition: str
    n: int
    pass_rate: float
    pass_rate_std: float  # across seeds
    repeated_failures: float
    requirement_violations: float
    interventions: float
    memory_tokens: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Report:
    results: list[TaskResult] = field(default_factory=list)
    summaries: list[ConditionSummary] = field(default_factory=list)


def summarize(results: list[TaskResult]) -> list[ConditionSummary]:
    by_condition: dict[str, list[TaskResult]] = {}
    for r in results:
        by_condition.setdefault(r.condition, []).append(r)

    summaries: list[ConditionSummary] = []
    for condition, rows in by_condition.items():
        # Pass rate per seed (over tasks), then mean/std of those across seeds.
        by_seed: dict[int, list[TaskResult]] = {}
        for r in rows:
            by_seed.setdefault(r.seed, []).append(r)
        seed_pass_rates = [
            sum(x.passed for x in seed_rows) / len(seed_rows) for seed_rows in by_seed.values()
        ]

        summaries.append(
            ConditionSummary(
                condition=condition,
                n=len(rows),
                pass_rate=statistics.fmean(seed_pass_rates),
                pass_rate_std=statistics.pstdev(seed_pass_rates)
                if len(seed_pass_rates) > 1
                else 0.0,
                repeated_failures=statistics.fmean([r.repeated_failures for r in rows]),
                requirement_violations=statistics.fmean([r.requirement_violations for r in rows]),
                interventions=statistics.fmean([r.interventions for r in rows]),
                memory_tokens=statistics.fmean([r.memory_tokens for r in rows]),
            )
        )

    # Stable, meaningful order.
    order = ["baseline", "injection_only", "full_bank", "always_inject", "agentmem"]
    summaries.sort(key=lambda s: order.index(s.condition) if s.condition in order else 99)
    return summaries
