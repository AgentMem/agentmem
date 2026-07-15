"""Run the Terminal-Bench 2.0 baseline-vs-memory comparison and print the verifier table."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentmem_evals.tbench.loop import is_self_hosted  # noqa: E402

AGENT_PATH = "agentmem_evals.tbench.harbor_agent:AgentMemTerminalAgent"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tasks", required=True, help="comma-separated task names")
    p.add_argument("--arms", default="baseline,memory")
    p.add_argument("--action-model", default="claude-haiku-4-5")
    p.add_argument("--memory-model", default="", help="defaults to the action model")
    p.add_argument("--max-turns", type=int, default=30)
    p.add_argument("--task-usd-cap", type=float, default=0.25)
    p.add_argument("--run-usd-cap", type=float, required=True)
    p.add_argument("--exec-timeout-sec", type=int, default=120)
    p.add_argument("--max-tokens", type=int, default=1024)
    p.add_argument("--api-base", default="", help="endpoint for a litellm/ self-hosted model")
    p.add_argument(
        "--no-thinking", action="store_true", help="disable a thinking model's reasoning trace"
    )
    p.add_argument("--tb-dir", required=True, help="downloaded terminal-bench task dir")
    p.add_argument("--jobs-dir", required=True)
    p.add_argument("--harbor-bin", default="harbor")
    p.add_argument("--n-concurrent", type=int, default=2)
    p.add_argument("--dry-run", action="store_true", help="print commands, run nothing")
    return p.parse_args()


def preflight(args: argparse.Namespace, tasks: list[str], arms: list[str]) -> None:
    needs_key = not is_self_hosted(args.action_model) or (
        "memory" in arms and not is_self_hosted(args.memory_model or args.action_model)
    )
    if needs_key and not os.environ.get("ANTHROPIC_API_KEY") and not args.dry_run:
        sys.exit("ANTHROPIC_API_KEY is not set; refusing to start a paid run.")
    tb = Path(args.tb_dir)
    missing = [t for t in tasks if not (tb / t / "task.toml").exists()]
    if missing:
        sys.exit(f"tasks not found under {tb}: {', '.join(missing)}")
    # Worst case: every trial burns its full per-task cap. The cap covers the whole
    # trial including memory-step calls (the loop counts both against it), so no
    # extra headroom factor is needed. A model you host yourself costs nothing per
    # token, so those runs are bounded by turns and by the task, not by money.
    free = is_self_hosted(args.action_model) and (
        "memory" not in arms or is_self_hosted(args.memory_model or args.action_model)
    )
    worst = 0.0 if free else args.task_usd_cap * len(tasks) * len(arms)
    if free:
        print("self-hosted models: no token cost, trials end on turns or on the task")
    print(f"worst-case spend: ${worst:.2f} (cap ${args.run_usd_cap:.2f})")
    if worst > args.run_usd_cap:
        sys.exit(
            "worst-case exceeds --run-usd-cap; lower --task-usd-cap, trim tasks, "
            "or raise the cap deliberately."
        )


def harbor_cmd(args: argparse.Namespace, arm: str, tasks: list[str], job: str) -> list[str]:
    cmd = [
        args.harbor_bin,
        "run",
        "-p",
        str(Path(args.tb_dir).expanduser()),
        "--agent",
        AGENT_PATH,
        "--ak",
        f"arm={arm}",
        "--ak",
        f"action_model={args.action_model}",
        "--ak",
        f"max_turns={args.max_turns}",
        "--ak",
        f"task_usd_cap={args.task_usd_cap}",
        "--ak",
        f"exec_timeout_sec={args.exec_timeout_sec}",
        "--ak",
        f"max_tokens={args.max_tokens}",
        "-o",
        str(Path(args.jobs_dir).expanduser()),
        "--job-name",
        job,
        "-n",
        str(args.n_concurrent),
        "-q",
        "-y",
    ]
    if args.memory_model:
        cmd += ["--ak", f"memory_model={args.memory_model}"]
    if args.api_base:
        cmd += ["--ak", f"api_base={args.api_base}"]
    if args.no_thinking:
        cmd += ["--ak", "no_thinking=true"]
    for t in tasks:
        cmd += ["-i", t]
    return cmd


def finalize_policy_dbs(jobs_dir: Path, job: str, results: dict[str, dict]) -> int:
    """Fold each trial's real verifier verdict into its recorded decisions.

    The agent closes its session before the verifier runs, so decisions get graded
    with task_reward 0. Adding gamma^(n-1-i) * reward afterwards makes g match what
    close() would have produced had it known the verdict."""
    import sqlite3

    gamma = 0.9
    updated = 0
    for db_path in sorted((jobs_dir / job).rglob("agentmem/policy.db")):
        task = next((p.name.split("__")[0] for p in db_path.parents if "__" in p.name), None)
        reward = 1.0 if task and results.get(task, {}).get("resolved") else 0.0
        db = sqlite3.connect(db_path)
        rows = db.execute("SELECT id FROM decisions WHERE g IS NOT NULL ORDER BY step").fetchall()
        n = len(rows)
        for i, (row_id,) in enumerate(rows):
            bonus = (gamma ** ((n - 1) - i)) * reward
            db.execute("UPDATE decisions SET g = g + ? WHERE id = ?", (bonus, row_id))
            updated += 1
        db.commit()
        db.close()
    return updated


def collect(jobs_dir: Path, job: str) -> dict[str, dict]:
    """task name -> {resolved, rewards, cost, turns, stop_reason} for one job.

    harbor 0.18 writes result.json (singular) at both the job and trial level; only
    trial-level files carry task_name, so anything without one is skipped."""
    out: dict[str, dict] = {}
    for rj in sorted((jobs_dir / job).rglob("result.json")):
        try:
            data = json.loads(rj.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        task = data.get("task_name")
        if not task:
            continue
        rewards = (data.get("verifier_result") or {}).get("rewards") or {}
        agent = data.get("agent_result") or {}
        meta = agent.get("metadata") or {}
        out[task] = {
            "resolved": any(v >= 1 for v in rewards.values()) if rewards else False,
            "rewards": rewards,
            "cost_usd": agent.get("cost_usd"),
            "turns": meta.get("turns"),
            "stop_reason": meta.get("stop_reason"),
            "reminders": meta.get("reminders_injected"),
            "exception": (data.get("exception_info") or {}).get("exception_type"),
        }
    return out


def main() -> None:
    args = parse_args()
    tasks = [t.strip() for t in args.tasks.split(",") if t.strip()]
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    preflight(args, tasks, arms)

    stamp = time.strftime("%m%d-%H%M%S")
    jobs_dir = Path(args.jobs_dir).expanduser()
    jobs_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, dict]] = {}

    for arm in arms:
        job = f"{stamp}-{arm}"
        cmd = harbor_cmd(args, arm, tasks, job)
        print(f"\n=== {arm}: {' '.join(cmd)}")
        if args.dry_run:
            continue
        proc = subprocess.run(cmd)
        if proc.returncode != 0:
            print(f"harbor exited {proc.returncode} for {arm}; collecting what exists.")
        results[arm] = collect(jobs_dir, job)
        if arm == "memory":
            n = finalize_policy_dbs(jobs_dir, job, results[arm])
            if n:
                dbs = f"{jobs_dir / job}/**/agentmem/policy.db"
                print(f"finalized {n} recorded decisions with real verdicts")
                print(f"AUC: python evals/longrun_sim/policy_auc.py {dbs}")

    if args.dry_run:
        return

    print(f"\n{'task':32} " + " ".join(f"{a:>10}" for a in arms) + "  cost/turns")
    passed = dict.fromkeys(arms, 0)
    spent = dict.fromkeys(arms, 0.0)
    for t in tasks:
        cells = []
        note = []
        for a in arms:
            r = results.get(a, {}).get(t)
            if r is None:
                cells.append(f"{'-':>10}")
                continue
            cells.append(f"{'PASS' if r['resolved'] else 'fail':>10}")
            passed[a] += 1 if r["resolved"] else 0
            spent[a] += r["cost_usd"] or 0.0
            note.append(f"{a}: ${r['cost_usd'] or 0:.2f}/{r['turns']}t/{r['stop_reason']}")
        print(f"{t:32} " + " ".join(cells) + "  " + "; ".join(note))
    print("\ntotals:")
    for a in arms:
        n = len(tasks)
        print(f"  {a:10} {passed[a]}/{n} passed   ${spent[a]:.2f} spent")

    report = {
        "stamp": stamp,
        "tasks": tasks,
        "arms": arms,
        "action_model": args.action_model,
        "memory_model": args.memory_model or args.action_model,
        "results": results,
        "passed": passed,
        "spent_usd": spent,
    }
    out = jobs_dir / f"report-{stamp}.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"\nreport: {out}")


if __name__ == "__main__":
    main()
