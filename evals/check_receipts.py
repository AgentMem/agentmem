#!/usr/bin/env python3
"""Recompute every headline number in the writeups from the committed artifacts.

A fabricated number would need a fabricated artifact, not just a sentence. Stdlib
only, so a bare python3 and CI can both run it:

    python3 evals/check_receipts.py [--write]
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "evals" / "report"


def _arms(path: Path) -> dict[str, Any]:
    return {r["condition"]: r for r in json.loads(path.read_text())}


def probe_numbers(path: Path) -> dict[str, Any]:
    g = _arms(path)
    return {
        "none_real": len(g["none"]["grounding"]["real"]),
        "none_invented": len(g["none"]["invented"]),
        "memory_real": len(g["memory"]["grounding"]["real"]),
        "memory_invented": len(g["memory"]["invented"]),
    }


def account_numbers(path: Path) -> dict[str, Any]:
    g = {r["condition"]: r for r in json.loads(path.read_text())}
    out = {}
    for arm in ("none", "memory"):
        for k in ("supported", "contradicted", "unverifiable"):
            out[f"{arm}_{k}"] = g[arm][k]
    return out


def repeat_numbers(path: Path) -> dict[str, Any]:
    g = _arms(path)
    return {
        "none_turns": g["none"]["waste"]["turns_wall_to_green"],
        "memory_turns": g["memory"]["waste"]["turns_wall_to_green"],
        "none_hits": g["none"]["waste"]["wall_hits"],
        "memory_hits": g["memory"]["waste"]["wall_hits"],
        # Zero here means the memory arm was the baseline wearing a label, which is
        # what turned attrs seed 1 into this project's only control.
        "reminders": g["memory"]["reminders_total"],
    }


def tau2_numbers(path: Path) -> dict[str, Any]:
    g = {r["arm"]: r for r in json.loads(path.read_text())}
    return {
        "none_passed": g["none"]["results"]["passed"],
        "memory_passed": g["memory"]["results"]["passed"],
        "n": g["none"]["results"]["n"],
        "boundaries": g["memory"]["ticket_boundaries"],
    }


def audit_numbers(path: Path) -> dict[str, Any]:
    d = json.loads(path.read_text())
    v = d["verdicts"]
    return {
        "interventions": d["citation_integrity"]["n"],
        "ids_match": d["citation_integrity"]["consistent"],
        "faithful": sum(1 for x in v if x.get("faithful") is True),
        "harmful": sum(1 for x in v if x.get("harmful") is True),
    }


class Claim:
    def __init__(
        self,
        writeup: str,
        label: str,
        artifact: str,
        compute: Callable[[Path], dict[str, Any]],
        expect: dict[str, Any],
        lost: str = "",
    ) -> None:
        self.writeup = writeup
        self.label = label
        self.artifact = artifact
        self.compute = compute
        self.expect = expect
        self.lost = lost

    def run(self) -> tuple[str, str]:
        path = REPORT / self.artifact
        if self.lost:
            return ("LOST", self.lost) if not path.exists() else ("FAIL", "marked lost but exists")
        if not path.exists():
            return "MISSING", f"{self.artifact} is not in the repo"
        got = self.compute(path)
        bad = {k: (v, got.get(k)) for k, v in self.expect.items() if got.get(k) != v}
        if bad:
            detail = "; ".join(f"{k}: claimed {c}, artifact says {a}" for k, (c, a) in bad.items())
            return "FAIL", detail
        return "OK", ", ".join(f"{k}={v}" for k, v in self.expect.items())


CLAIMS = [
    Claim(
        "evals/realworld/RESULTS.md",
        "click run 1: 0/4 vs 5/0",
        "realworld-probe.json",
        probe_numbers,
        {"none_real": 0, "none_invented": 4, "memory_real": 5, "memory_invented": 0},
    ),
    Claim(
        "evals/realworld/RESULTS.md",
        "click run 2: 0/3 vs 4/1",
        "realworld-probe-click-r2.json",
        probe_numbers,
        {"none_real": 0, "none_invented": 3, "memory_real": 4, "memory_invented": 1},
    ),
    Claim(
        "evals/realworld/RESULTS.md",
        "attrs: 0/3 vs 2/0",
        "realworld-probe-attrs.json",
        probe_numbers,
        {"none_real": 0, "none_invented": 3, "memory_real": 2, "memory_invented": 0},
    ),
    Claim(
        "evals/realworld/RESULTS.md",
        "more-itertools: 0/4 vs 5/0",
        "realworld-probe-more-itertools.json",
        probe_numbers,
        {"none_real": 0, "none_invented": 4, "memory_real": 5, "memory_invented": 0},
    ),
    Claim(
        "evals/realworld/RESULTS.md",
        "ledger, click r2",
        "account-click-r2.json",
        account_numbers,
        {
            "none_supported": 0,
            "none_contradicted": 2,
            "memory_supported": 1,
            "memory_contradicted": 0,
            "memory_unverifiable": 1,
        },
    ),
    Claim(
        "evals/realworld/RESULTS.md",
        "ledger, attrs",
        "account-attrs.json",
        account_numbers,
        {
            "none_supported": 0,
            "none_contradicted": 3,
            "memory_supported": 1,
            "memory_contradicted": 0,
        },
    ),
    Claim(
        "evals/realworld/RESULTS.md",
        "ledger, more-itertools",
        "account-more-itertools.json",
        account_numbers,
        {
            "none_supported": 0,
            "none_contradicted": 2,
            "memory_supported": 1,
            "memory_contradicted": 1,
        },
    ),
    Claim(
        "evals/repeat/RESULTS.md",
        "seed 1: 20 vs 13",
        "repeat-click-s1.json",
        repeat_numbers,
        {"none_turns": 20, "memory_turns": 13, "none_hits": 2, "memory_hits": 1, "reminders": 3},
    ),
    Claim(
        "evals/repeat/RESULTS.md",
        "seed 2: 14 vs 12",
        "repeat-click-s2.json",
        repeat_numbers,
        {"none_turns": 14, "memory_turns": 12, "none_hits": 2, "memory_hits": 2, "reminders": 4},
    ),
    Claim(
        "evals/repeat/RESULTS.md",
        "seed 3: 17 vs 8",
        "repeat-click-s3.json",
        repeat_numbers,
        {"none_turns": 17, "memory_turns": 8, "none_hits": 1, "memory_hits": 1, "reminders": 5},
    ),
    Claim(
        "evals/repeat/RESULTS.md",
        "attrs 1: the accidental control, 22 vs 12 on zero reminders",
        "repeat-attrs-s1.json",
        repeat_numbers,
        {"none_turns": 22, "memory_turns": 12, "reminders": 0},
    ),
    Claim(
        "evals/repeat/RESULTS.md",
        "attrs 2: 16 vs 13",
        "repeat-attrs-s2.json",
        repeat_numbers,
        {"none_turns": 16, "memory_turns": 13, "reminders": 2},
    ),
    Claim(
        "evals/audit/RESULTS.md",
        "repeat reminders: 12/12 at temperature 0",
        "audit-repeat.json",
        audit_numbers,
        {"interventions": 12, "ids_match": 12, "faithful": 12, "harmful": 0},
    ),
    Claim(
        "evals/tau2/RESULTS.md",
        "airline 50: 37 vs 38, net +1",
        "tau2-airline-full.json",
        tau2_numbers,
        {"none_passed": 37, "memory_passed": 38, "n": 50, "boundaries": 50},
    ),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write", action="store_true", help="regenerate evals/RECEIPTS.md")
    args = ap.parse_args()

    rows = []
    worst = "OK"
    for c in CLAIMS:
        status, detail = c.run()
        rows.append((c, status, detail))
        if status in ("FAIL", "MISSING"):
            worst = "FAIL"
        print(f"  {status:7} {c.label:44} {c.artifact}")
        if status != "OK":
            print(f"          {detail}")

    if args.write:
        lines = [
            "# Receipts",
            "",
            "Every headline number, the committed artifact it is computed from, and the",
            "check that recomputes it. Regenerate this table and verify every row with:",
            "",
            "    python3 evals/check_receipts.py --write",
            "",
            "A row can be OK (recomputed and equal), FAIL (the writeup and the artifact",
            "disagree, which blocks), or LOST (the artifact no longer exists and the",
            "writeup says so in plain sight rather than hoping nobody asks).",
            "",
            "| status | claim | writeup | artifact |",
            "|---|---|---|---|",
        ]
        for c, status, _ in rows:
            lines.append(f"| {status} | {c.label} | {c.writeup} | `evals/report/{c.artifact}` |")
        lines += [
            "",
            "What this does and does not prove: it proves the prose matches the raw run",
            "records, so inventing a number requires inventing an artifact, not a sentence.",
            "It cannot prove the artifacts themselves were not fabricated; nothing can.",
            "What makes fabrication a bad bet here is that every run is reproducible from",
            "a pinned command in its writeup, on open weights, mostly at zero API cost,",
            "so any reader can spend a few dollars and catch us. Cheap to check beats",
            "trust me.",
            "",
        ]
        (ROOT / "evals" / "RECEIPTS.md").write_text("\n".join(lines))
        print("\nwrote evals/RECEIPTS.md")

    return 1 if worst == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
