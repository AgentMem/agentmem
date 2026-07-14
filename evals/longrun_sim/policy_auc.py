"""Score the advantage layer against realized outcomes: leave-one-out AUC over policy DBs."""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "agentmem" / "src"))

from agentmem.policy.advantage import estimate  # noqa: E402
from agentmem.policy.policy_store import DecisionRecord  # noqa: E402


def load_records(paths: list[str]) -> list[DecisionRecord]:
    out: list[DecisionRecord] = []
    for p in paths:
        db = sqlite3.connect(p)
        rows = db.execute(
            "SELECT session_id, step, state_sig, action, inject_class, model, g "
            "FROM decisions WHERE g IS NOT NULL"
        ).fetchall()
        db.close()
        for sid, step, sig, action, klass, model, g in rows:
            out.append(
                DecisionRecord(
                    session_id=f"{p}:{sid}",
                    step=step,
                    state_sig=json.loads(sig),
                    action=action,
                    inject_class=klass,
                    model=model,
                    g=g,
                )
            )
    return out


def loo_scores(records: list[DecisionRecord]) -> list[tuple[float, float]]:
    """(predicted advantage of the taken action, realized g) per record, self excluded."""
    pairs: list[tuple[float, float]] = []
    for i, r in enumerate(records):
        rest = records[:i] + records[i + 1 :]
        adv = estimate(r.state_sig, rest)
        if adv is None:
            continue
        a_hat = adv.a_inject if r.action == "inject" else adv.a_silent
        pairs.append((a_hat, r.g))
    return pairs


def auc(pairs: list[tuple[float, float]], cut: float) -> float | None:
    """Mann-Whitney AUC of the score ranking outcomes above the cut."""
    pos = [s for s, g in pairs if g > cut]
    neg = [s for s, g in pairs if g <= cut]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def bootstrap_ci(
    pairs: list[tuple[float, float]], cut: float, n: int = 1000
) -> tuple[float, float]:
    rng = random.Random(7)
    vals = []
    for _ in range(n):
        sample = [pairs[rng.randrange(len(pairs))] for _ in pairs]
        a = auc(sample, cut)
        if a is not None:
            vals.append(a)
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals))]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="AUC of the advantage layer over policy DBs")
    ap.add_argument("dbs", nargs="+", help="policy.db paths")
    args = ap.parse_args(argv)

    records = load_records(args.dbs)
    n_inject = sum(1 for r in records if r.action == "inject")
    print(
        f"finalized decisions: {len(records)} ({n_inject} inject / {len(records) - n_inject} silent)"
    )
    if len(records) < 20:
        print("too few records for a meaningful AUC; collect more runs")
        return 1

    pairs = loo_scores(records)
    print(f"scored (had neighbors): {len(pairs)}")
    gs = sorted(g for _, g in pairs)
    if gs[0] == gs[-1]:
        print(f"all outcomes identical (g={gs[0]:.2f}); AUC needs outcome variance")
        return 1
    # Cut at zero and at the midrange; the median of a skewed pile can sit on the max.
    mid = (gs[0] + gs[-1]) / 2
    for name, cut in (("g > 0", 0.0), (f"g > midrange ({mid:.2f})", mid)):
        a = auc(pairs, cut)
        if a is None:
            print(f"AUC [{name}]: undefined (cut leaves one side empty)")
            continue
        lo, hi = bootstrap_ci(pairs, cut)
        print(f"AUC [{name}]: {a:.3f}  (95% bootstrap CI {lo:.3f}-{hi:.3f})")
    print("gate for the trained policy (M7b): AUC >= 0.6 on >= 500 labeled steps")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
