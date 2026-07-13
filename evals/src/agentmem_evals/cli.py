"""agentmem-evals: run the ablation and write a report.

Offline by default (scripted agent, no key, no cost). `--live` uses a real model and
should always be paired with `--max-usd`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .budget import BudgetExceeded, UsdBudget
from .conditions import CONDITIONS
from .metrics import Report
from .report import write_report
from .runner import run_task
from .task import discover_tasks

_DEFAULT_TASKS = Path(__file__).resolve().parents[2] / "longdebug_mini" / "tasks"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentmem-evals", description=__doc__)
    parser.add_argument("--condition", default="all", help=f"one of {CONDITIONS}, or 'all'")
    parser.add_argument("--seeds", type=int, default=3, help="repeats per (task, condition)")
    parser.add_argument("--task", default=None, help="run a single task by id")
    parser.add_argument(
        "--live", action="store_true", help="use a real model (needs ANTHROPIC_API_KEY)"
    )
    parser.add_argument("--model-mem", default="claude-haiku-4-5", help="memory-agent model")
    parser.add_argument("--max-usd", type=float, default=None, help="hard spend cap for live runs")
    parser.add_argument("--tasks-dir", default=str(_DEFAULT_TASKS))
    parser.add_argument("--out", default="evals/report", help="report output directory")
    args = parser.parse_args(argv)

    tasks = discover_tasks(args.tasks_dir)
    if args.task:
        tasks = [t for t in tasks if t.id == args.task]
    if not tasks:
        parser.error(f"no tasks found under {args.tasks_dir}")

    conditions = CONDITIONS if args.condition == "all" else [args.condition]
    offline = not args.live
    budget = UsdBudget(args.max_usd)

    if args.live and args.max_usd is None:
        print("warning: --live without --max-usd has no spend cap.\n")

    results = []
    stopped = False
    for seed in range(args.seeds):
        for task in tasks:
            for condition in conditions:
                try:
                    r = run_task(
                        task,
                        condition,
                        seed,
                        offline=offline,
                        memory_model=args.model_mem,
                        budget=budget,
                    )
                except BudgetExceeded as exc:
                    print(f"[budget] stopping early: {exc}")
                    stopped = True
                    break
                results.append(r)
                print(
                    f"seed {seed}  {task.id:14} {condition:14} "
                    f"pass={'Y' if r.passed else 'n'}  repeats={r.repeated_failures}  "
                    f"violations={r.requirement_violations}  interventions={r.interventions}"
                )
            if stopped:
                break
        if stopped:
            break

    from .metrics import summarize

    report = Report(results=results, summaries=summarize(results))
    out = write_report(
        report,
        Path(args.out),
        meta={
            "mode": "offline" if offline else "live",
            "seeds": args.seeds,
            "tasks": len(tasks),
            "memory_model": args.model_mem if not offline else "scripted",
            "spent_usd": round(budget.spent, 4),
        },
    )
    print(f"\nReport written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
