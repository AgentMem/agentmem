"""Build the 30-session LongRun-sim schedule and load its retention probes."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

REPOS = ("a", "b", "c")
SESSIONS_PER_REPO = 10
PROBE_DIR = Path(__file__).parent / "probes"


@dataclass
class ScheduledSession:
    index: int  # 0-based position in the run
    repo: str


@dataclass
class Probe:
    id: str
    repo: str
    question: str
    answer_contains: list[str]
    forbidden: list[str]


def schedule(
    repos: tuple[str, ...] = REPOS, per_repo: int = SESSIONS_PER_REPO
) -> list[ScheduledSession]:
    """Round-robin the repos so consecutive sessions never share one."""
    out: list[ScheduledSession] = []
    for _ in range(per_repo):
        for repo in repos:
            out.append(ScheduledSession(index=len(out), repo=repo))
    return out


def load_probes(repo: str) -> list[Probe]:
    spec = yaml.safe_load((PROBE_DIR / f"repo_{repo}.yaml").read_text())
    return [
        Probe(
            id=p["id"],
            repo=repo,
            question=p["question"],
            answer_contains=list(p.get("answer_contains", [])),
            forbidden=list(p.get("forbidden", [])),
        )
        for p in spec.get("probes", [])
    ]


def all_probes() -> list[Probe]:
    return [p for repo in REPOS for p in load_probes(repo)]


def _selftest() -> int:
    runs = schedule()
    assert len(runs) == len(REPOS) * SESSIONS_PER_REPO == 30
    for a, b in zip(runs, runs[1:], strict=False):
        assert a.repo != b.repo, "consecutive sessions must be on different repos"
    for repo in REPOS:
        assert sum(s.repo == repo for s in runs) == SESSIONS_PER_REPO

    probes = all_probes()
    assert len(probes) == 9, "three probes per repo"
    assert {p.repo for p in probes} == set(REPOS)
    assert all(p.question and p.answer_contains for p in probes)

    print("selftest: OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LongRun-sim schedule + probes")
    parser.add_argument("--selftest", action="store_true", help="validate offline")
    parser.add_argument("--print", action="store_true", help="print the session schedule")
    args = parser.parse_args(argv)
    if args.selftest:
        return _selftest()
    if args.print:
        for s in schedule():
            print(f"session {s.index:2d}: repo {s.repo}")
        return 0
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
