#!/usr/bin/env python3
"""Score causal run reports: is each root-cause answer anchored in the real project?"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import grounding as G  # noqa: E402
import judge_prompts as J  # noqa: E402
import smoke as SM  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("reports", nargs="+", help="causal-live-*.json")
    ap.add_argument("--verbose", action="store_true", help="print each answer's citations")
    args = ap.parse_args()

    tally: dict[str, list[int]] = {}
    rows = []
    for path in args.reports:
        seed = Path(path).stem.split("-")[-1]
        for r in json.loads(Path(path).read_text()):
            tid, cond = r["task_id"], r["condition"]
            repo = HERE / SM.task_dir(tid) / "repo"
            gr = G.score(r["wrapup_answer"] or "", repo)
            gold = J.load_gold(HERE / "gold" / f"{tid}.yaml")
            kw, _ = J.keyword_gate(r["wrapup_answer"] or "", gold)
            t = tally.setdefault(cond, [0, 0, 0])
            t[0] += 1
            t[1] += 1 if gr["grounded"] else 0
            t[2] += 1 if kw else 0
            rows.append((seed, tid, cond, gr, kw))

    print(f"{'seed':5} {'task':7} {'cond':7} {'grounded':>9} {'gate':>5}  cited")
    for seed, tid, cond, gr, kw in rows:
        cited = ", ".join(gr["real"][:3]) if args.verbose else f"{gr['n_real']} real"
        print(
            f"{seed:5} {tid:7} {cond:7} {('YES' if gr['grounded'] else 'no'):>9} "
            f"{('PASS' if kw else 'fail'):>5}  {cited}"
        )

    print("\nAnswers anchored in the real project (the metric that survives inspection):")
    for cond, (n, g, k) in sorted(tally.items()):
        print(f"  {cond:7} grounded {g}/{n}   keyword gate {k}/{n}")
    print(
        "\nThe gate is reported for continuity only; it has produced both false negatives\n"
        "and a false positive on this data, so it is not the number to quote."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
