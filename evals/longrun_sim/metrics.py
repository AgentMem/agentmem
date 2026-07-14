"""Scoring for LongRun-sim: retention, interference, and bank growth."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field


@dataclass
class SessionRecord:
    """One simulated session's outcome, produced by the live runner."""

    repo: str
    index: int  # 0-based position in the interleaved schedule
    passed: bool  # pass@1: did the agent solve it on the first attempt
    repeated_failures: int  # same command/error tried more than once
    bank_size: int  # live entries after the session
    cited_repos: list[str] = field(default_factory=list)  # repo each cited entry belongs to


@dataclass
class ProbeResult:
    """One retention probe: a hidden question about a repo's requirements, answered
    from memory. `correct` is graded by the judge."""

    repo: str
    at_session: int
    correct: bool


def retention_rate(probes: list[ProbeResult], at_session: int | None = None) -> float:
    """Share of retention probes answered correctly. With `at_session`, only probes
    fired at that point count, which is how the "≥90% at session 30" bar is read."""
    pool = [p for p in probes if at_session is None or p.at_session == at_session]
    if not pool:
        return 0.0
    return sum(p.correct for p in pool) / len(pool)


def interference_rate(records: list[SessionRecord]) -> float:
    """Share of cited entries that belong to a different repo than the one being
    worked. This is the negative-transfer signal; we want it under 5%."""
    total = crossed = 0
    for r in records:
        for repo in r.cited_repos:
            total += 1
            if repo != r.repo:
                crossed += 1
    return crossed / total if total else 0.0


def learning_curve_slope(records: list[SessionRecord]) -> float:
    """Slope of pass@1 against session index. Positive means the agent is getting
    better at these repos over time, not just holding steady."""
    points = [(float(r.index), 1.0 if r.passed else 0.0) for r in records]
    return _slope(points)


def repeated_failure_slope(records: list[SessionRecord]) -> float:
    """Slope of repeated-failure count over time. We want it negative: the agent
    should stop re-making the same mistakes as memory fills in."""
    points = [(float(r.index), float(r.repeated_failures)) for r in records]
    return _slope(points)


def bank_growth_ratio(records: list[SessionRecord]) -> float:
    """Final bank size over the midpoint size. Continual memory should keep this near
    1.0 (bounded); a value climbing with the session count means nothing is forgotten."""
    sized = [r.bank_size for r in sorted(records, key=lambda r: r.index)]
    if len(sized) < 2:
        return 1.0
    mid = sized[len(sized) // 2] or 1
    return sized[-1] / mid


def _slope(points: list[tuple[float, float]]) -> float:
    """Ordinary least-squares slope. Zero when x never varies."""
    n = len(points)
    if n < 2:
        return 0.0
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in points)
    den = sum((x - mean_x) ** 2 for x, _ in points)
    return num / den if den else 0.0


# Bars the live run is expected to clear (LongRun-sim over 30 sessions, 3 repos).
RETENTION_MIN = 0.90
INTERFERENCE_MAX = 0.05
BANK_GROWTH_MAX = 1.5


def _selftest() -> int:
    # A rising pass@1 with falling repeats, no cross-repo citations, stable bank.
    records = [
        SessionRecord(
            repo=["a", "b", "c"][i % 3],
            index=i,
            passed=i >= 6,
            repeated_failures=max(0, 5 - i),
            bank_size=10 + min(i, 8),
            cited_repos=[["a", "b", "c"][i % 3]],
        )
        for i in range(12)
    ]
    assert learning_curve_slope(records) > 0, "pass@1 should trend up"
    assert repeated_failure_slope(records) < 0, "repeats should trend down"
    assert interference_rate(records) == 0.0, "no cross-repo citations here"

    dirty = records + [
        SessionRecord(
            repo="a", index=12, passed=True, repeated_failures=0, bank_size=18, cited_repos=["b"]
        )
    ]
    assert interference_rate(dirty) > 0, "a cross-repo citation must register"

    probes = [ProbeResult(repo="a", at_session=30, correct=True) for _ in range(9)]
    probes.append(ProbeResult(repo="a", at_session=30, correct=False))
    assert retention_rate(probes, at_session=30) == 0.9
    assert bank_growth_ratio(records) < BANK_GROWTH_MAX

    print("selftest: OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LongRun-sim scoring")
    parser.add_argument("--selftest", action="store_true", help="check the math offline")
    args = parser.parse_args(argv)
    if args.selftest:
        return _selftest()
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
