#!/usr/bin/env python3
"""Run tau2-bench twice on the same tasks: tau2's agent bare, then with memory.

Runs inside the tau2 venv (see evals/tau2/README.md), because tau2 needs Python
3.12 and this repo is 3.11.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentmem.config import AgentMemConfig
from agentmem.session import MemorySession
from agentmem.triggers import default as default_trigger
from agentmem_evals.tau2.agent import MemoryRun, register_agentmem_agent
from agentmem_evals.tbench.loop import CountingProvider, is_self_hosted

BASELINE_AGENT = "llm_agent"  # tau2's own, unmodified


def build_memory_provider(model: str, api_base: str, no_thinking: bool):  # noqa: ANN201
    if model.startswith("litellm/"):
        from agentmem.llm.litellm import LiteLLMProvider

        return LiteLLMProvider(
            model=model.removeprefix("litellm/"),
            api_base=api_base or None,
            timeout=300.0,
            extra_body=(
                {"chat_template_kwargs": {"enable_thinking": False}} if no_thinking else None
            ),
        )
    from agentmem.llm.anthropic import AnthropicProvider

    return AnthropicProvider(model=model, timeout=300.0)


def make_run(args: argparse.Namespace, state_dir: Path) -> tuple[MemoryRun, list]:
    """One session for the whole domain, one state dir. See MemoryRun for why the
    session is not per ticket."""
    provider = CountingProvider(
        build_memory_provider(args.memory_model, args.api_base, args.no_thinking)
    )
    session = MemorySession(
        task="Handle customer service tickets in this domain",
        provider=provider,
        trigger=default_trigger(),
        async_worker=False,
        session_id=f"tau2-{args.domain}-{args.seed_tag}",
        config=AgentMemConfig(
            state_dir=str(state_dir), advantage_enabled=True, advantage_gate=False
        ),
    )
    return MemoryRun(session), [provider]


def _refuse_a_warm_bank(state_dir: Path, resume: bool) -> None:
    """Stop rather than quietly start the memory arm with a bank it already filled.

    A state dir is keyed by domain and seed tag, so re-running the same command after
    a crash, or after a first look at the numbers, hands the memory arm everything it
    learned last time while the baseline starts from nothing. The run still completes
    and the report still looks ordinary. Nothing about the output says the two arms
    were no longer comparable, which is why this is an error and not a warning.
    """
    if resume or not state_dir.exists():
        return
    leftovers = [p for p in state_dir.rglob("*") if p.is_file()]
    if not leftovers:
        return
    print(f"\nERROR: {state_dir} already holds a bank from an earlier run:")
    for p in leftovers[:5]:
        print(f"  {p.relative_to(state_dir)}")
    print("\nStarting on top of it would give the memory arm a head start the baseline")
    print("does not get, and the report would not show it. Pick a new --seed-tag, or")
    print("delete that directory, or pass --resume if continuing is what you meant.")
    raise SystemExit(2)


def run_arm(arm: str, args: argparse.Namespace, tasks: list) -> dict:
    from tau2.data_model.simulation import TextRunConfig
    from tau2.runner.batch import run_tasks

    llm_args = {"temperature": 0.0}
    if args.api_base:
        llm_args["api_base"] = args.api_base

    run, counters = (None, [])
    agent_name = BASELINE_AGENT
    concurrency = args.max_concurrency
    if arm == "memory":
        state_dir = Path(args.state_dir) / f"tau2-{args.domain}-{args.seed_tag}"
        _refuse_a_warm_bank(state_dir, args.resume)
        run, counters = make_run(args, state_dir)
        agent_name = register_agentmem_agent(run, name="agentmem")
        # One bank, one ticket at a time. Two tickets at once would interleave two
        # conversations into it, and the order notes were learned in, which is the
        # thing being measured, would stop meaning anything.
        if concurrency != 1:
            print(f"  memory arm: forcing max_concurrency 1 (asked for {concurrency})")
            concurrency = 1

    config = TextRunConfig(
        domain=args.domain,
        agent=agent_name,
        llm_agent=args.action_model,
        llm_args_agent=dict(llm_args),
        user="user_simulator",
        llm_user=args.user_model,
        llm_args_user=dict(llm_args),
        task_split_name=args.task_split,
        num_trials=args.num_trials,
        max_steps=args.max_steps,
        max_concurrency=concurrency,
    )

    save_dir = Path(args.out_dir) / f"{args.domain}-{arm}-{args.seed_tag}"
    save_dir.mkdir(parents=True, exist_ok=True)
    try:
        if run is None:
            results = run_tasks(config, tasks, save_dir=save_dir, console_display=False)
        else:
            results = _run_tickets_in_order(config, tasks, save_dir, run)
        tickets_ended = run.tickets_ended if run is not None else 0
    finally:
        if run is not None:
            run.close()
    memory_usd = sum(c.spent_usd for c in counters if hasattr(c, "spent_usd"))
    return {
        "arm": arm,
        "agent": agent_name,
        "domain": args.domain,
        "n_tasks": len(tasks),
        "memory_usd": round(memory_usd, 4),
        "ticket_boundaries": tickets_ended,
        "results": _summarize(results),
        "save_dir": str(save_dir),
    }


def _run_tickets_in_order(config: object, tasks: list, save_dir: Path, run: MemoryRun) -> object:
    """One ticket at a time, closing each with the score it actually got.

    The baseline arm goes through tau2's batch runner, which is faster and does the
    same thing for an agent with no memory. The memory arm cannot: the batch runner
    reports every score at the end, and by then it is too late to tell the memory
    layer which of its reminders were worth keeping. Scoring each ticket as it lands
    is what makes the reward real instead of a placeholder zero.
    """
    from tau2.data_model.simulation import Results
    from tau2.runner.batch import run_single_task
    from tau2.runner.helpers import get_info

    sims = []
    for i, task in enumerate(tasks, start=1):
        try:
            sim = run_single_task(config, task, save_dir=save_dir)
        except Exception as exc:  # a ticket that blows up must not end the run
            print(f"  ticket {i}/{len(tasks)} {task.id}: failed ({type(exc).__name__}: {exc})")
            continue
        reward = getattr(getattr(sim, "reward_info", None), "reward", None)
        sims.append(sim)
        run.end_ticket(float(reward) if reward is not None else 0.0)
        if i % 10 == 0 or i == len(tasks):
            print(f"  ticket {i}/{len(tasks)}: last reward {reward}")
    # tau2's own get_info, because Results requires it and hand-rolling one here would
    # be a second, worse copy of a struct that records what produced these numbers.
    return Results(info=get_info(config), tasks=tasks, simulations=sims)


def _summarize(results: object) -> dict:
    """tau2's Results, reduced to what an arm is judged on, plus what it cost.

    The per-task verdicts are kept so the two arms can be compared task by task.
    A pass rate alone cannot tell a real gain from an even trade, and an even trade
    is exactly what the terminal-bench runs turned out to be."""
    sims = getattr(results, "simulations", None) or []
    per_task: dict[str, float] = {}
    cost = 0.0
    for sim in sims:
        info = getattr(sim, "reward_info", None)
        reward = getattr(info, "reward", None) if info is not None else None
        if reward is not None:
            per_task[str(getattr(sim, "task_id", "?"))] = float(reward)
        cost += float(getattr(sim, "agent_cost", 0.0) or 0.0)
    passed = sum(1 for r in per_task.values() if r >= 1.0)
    return {
        "n": len(per_task),
        "passed": passed,
        "pass_rate": round(passed / len(per_task), 4) if per_task else None,
        "agent_usd": round(cost, 4),
        "per_task": per_task,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--domain", default="airline")
    ap.add_argument("--arms", default="none,memory")
    ap.add_argument("--action-model", required=True)
    ap.add_argument("--user-model", default="")
    ap.add_argument("--memory-model", default="")
    ap.add_argument("--api-base", default="")
    ap.add_argument("--task-split", default="base")
    ap.add_argument("--num-tasks", type=int, default=0, help="0 runs the whole split")
    ap.add_argument("--num-trials", type=int, default=1)
    ap.add_argument("--max-steps", type=int, default=100)
    ap.add_argument("--max-concurrency", type=int, default=4)
    ap.add_argument("--no-thinking", action="store_true")
    ap.add_argument("--seed-tag", default="s1")
    ap.add_argument("--resume", action="store_true", help="continue on top of an existing bank")
    ap.add_argument("--state-dir", default="")
    ap.add_argument("--out-dir", default="")
    ap.add_argument("--out", default="tau2-report.json")
    args = ap.parse_args()
    args.user_model = args.user_model or args.action_model
    args.memory_model = args.memory_model or args.action_model
    args.state_dir = args.state_dir or "./tau2-state"
    args.out_dir = args.out_dir or "./tau2-runs"

    models = (args.action_model, args.user_model, args.memory_model)
    hosted = [m for m in models if not is_self_hosted(m)]
    if hosted:
        print(f"note: billed per token, these are not self-hosted: {sorted(set(hosted))}")
    else:
        print("action, user simulator and memory are all self-hosted: $0 in API spend")

    from tau2.runner.helpers import get_tasks

    tasks = get_tasks(
        task_set_name=args.domain,
        task_split_name=args.task_split,
        num_tasks=args.num_tasks or None,
    )
    print(f"domain {args.domain}, split {args.task_split}: {len(tasks)} tasks")
    print(f"action={args.action_model}  user={args.user_model}  memory={args.memory_model}")

    out = []
    for arm in [a.strip() for a in args.arms.split(",") if a.strip()]:
        print(f"== {arm}")
        out.append(run_arm(arm, args, tasks))
        r = out[-1]["results"]
        print(f"  {arm}: {r['passed']}/{r['n']} pass_rate={r['pass_rate']}")

    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"\nreport: {args.out}")
    if len(out) == 2:
        _report_pairs(out[0], out[1])
    return 0


def _report_pairs(none_arm: dict, mem_arm: dict) -> None:
    """Which tasks each arm won, not just how many. A run where memory fixes four
    tasks and breaks four is not the same as a run where nothing moved, and a pass
    rate reports them identically."""
    a, b = none_arm["results"]["per_task"], mem_arm["results"]["per_task"]
    shared = sorted(set(a) & set(b))
    gained = [t for t in shared if a[t] < 1.0 <= b[t]]
    lost = [t for t in shared if b[t] < 1.0 <= a[t]]
    # The baseline goes through tau2's batch runner, which retries a ticket that
    # errors; the memory arm runs them one at a time and drops one that raises. A
    # ticket missing from either arm is dropped from the pairing, so this does not
    # bend the comparison, but it does cost tickets and the count should be visible
    # rather than inferred from a smaller n.
    only_none = sorted(set(a) - set(b))
    only_mem = sorted(set(b) - set(a))
    if only_none or only_mem:
        print(
            f"\nunpaired and therefore ignored: {len(only_none)} the memory arm lost, "
            f"{len(only_mem)} the baseline lost"
        )
    print(f"\npaired on {len(shared)} tasks")
    print(f"  fail -> pass with memory: {len(gained)}  {gained[:6]}")
    print(f"  pass -> fail with memory: {len(lost)}  {lost[:6]}")
    print(f"  net: {len(gained) - len(lost):+d}")
    print(
        f"  agent spend: none ${none_arm['results']['agent_usd']:.4f} "
        f"vs memory ${mem_arm['results']['agent_usd']:.4f} "
        f"+ ${mem_arm['memory_usd']:.4f} on the memory layer itself"
    )
    if len(gained) + len(lost) < 10:
        print("  too few tasks moved either way to call this anything but noise")


if __name__ == "__main__":
    raise SystemExit(main())
