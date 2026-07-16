#!/usr/bin/env python3
"""Does an agent that lost its context pay to rediscover what it already fixed?

Same shape as evals/realworld: a real upstream repo, real bit-rot, nothing planted.
Session 1 walks into click's pytest collection failure and fixes it. Two chores pass.
Then an ordinary git move throws the uncommitted fix away and the wall is back, with
the context that learned it gone. The question is what that costs.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "packages" / "agentmem" / "src"))
sys.path.insert(0, str(HERE.parents[1] / "evals" / "src"))
sys.path.insert(0, str(HERE.parents[0] / "realworld"))

from agentmem.config import AgentMemConfig  # noqa: E402
from agentmem.session import MemorySession  # noqa: E402
from agentmem.triggers import default as default_trigger  # noqa: E402
from agentmem_evals.tbench.loop import ActionLoop, CountingProvider, is_self_hosted  # noqa: E402
from run_probe import Box, build_provider  # noqa: E402

TURN_CAP = 25


def waste(calls: list[dict[str, Any]], wall_re: str, green_re: str) -> dict[str, Any]:
    """What the last session cost, from the transcript of its own commands.

    Both numbers are counted, not modelled. The compaction eval infers whether a
    rerun was pointless from the tool that ran between, which needs a notion of
    which tools mutate; this loop only has bash, so that notion would be a guess
    about what a shell command did. Hitting the wall is visible in its output, and
    turns are turns.
    """
    wall, green = re.compile(wall_re), re.compile(green_re)
    wall_at = green_at = None
    hits = 0
    for i, c in enumerate(calls):
        if wall.search(c["output"]):
            hits += 1
            if wall_at is None:
                wall_at = i
        if wall_at is not None and green_at is None and green.search(c["output"]):
            green_at = i
    return {
        "wall_hit": wall_at is not None,
        "wall_hits": hits,
        "recovered": green_at is not None,
        # Both, not just green_at: the loop only sets green_at after a wall hit, but
        # that invariant lives in the loop and not here.
        "turns_wall_to_green": (
            green_at - wall_at + 1 if green_at is not None and wall_at is not None else None
        ),
        "turns_in_session": len(calls),
    }


def run_condition(
    cond: str, args: argparse.Namespace, spec: dict[str, Any], root: Path
) -> dict[str, Any]:
    workdir = root / f"repo-{cond}"
    box = Box(spec["repo"], spec["ref"], workdir, spec.get("test_deps", ""))
    box.up()
    mem_state = root / f"mem-{cond}"
    sessions: list[dict[str, Any]] = []
    memory = None
    try:
        for i, ticket in enumerate(spec["sessions"], start=1):
            if cond == "memory":
                # A session per ticket, against one state dir: the context resets, the
                # bank does not. That reset is the whole experiment.
                memory = MemorySession(
                    task="Maintain this project across sessions",
                    provider=CountingProvider(build_provider(args.memory_model, args.api_base)),
                    trigger=default_trigger(),
                    async_worker=False,
                    session_id=f"repeat-{cond}-{i}",
                    config=AgentMemConfig(
                        state_dir=str(mem_state), advantage_enabled=True, advantage_gate=False
                    ),
                )
            loop = ActionLoop(
                CountingProvider(build_provider(args.action_model, args.api_base)),
                f"You maintain the project in /work. Work this ticket, then task_done.\n\n"
                f"Ticket: {ticket}",
                memory=memory,
                max_turns=TURN_CAP,
                usd_cap=args.session_usd_cap,
                max_tokens=args.max_tokens,
            )
            calls: list[dict[str, Any]] = []
            while True:
                d = loop.next_decision()
                if d.kind != "exec":
                    break
                code, out = box.exec(d.command)
                calls.append({"command": d.command, "output": out[:4000], "code": code})
                loop.record_exec(d, out, "", code)
            if memory is not None:
                memory.close(task_reward=0.0)
            sessions.append(
                {
                    "ticket": ticket[:70],
                    "turns": loop.turns,
                    "stop": loop.stop_reason,
                    "reminders": getattr(loop, "reminders_injected", 0),
                    "calls": calls,
                }
            )
            print(f"  {cond} s{i}: turns={loop.turns} {loop.stop_reason}", flush=True)
    finally:
        box.down()

    last = sessions[-1]["calls"] if sessions else []
    return {
        "condition": cond,
        "sessions": [{k: v for k, v in s.items() if k != "calls"} for s in sessions],
        "final_session_calls": last,
        "waste": waste(last, spec["wall_re"], spec["green_re"]),
        "reminders_total": sum(s["reminders"] for s in sessions),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tickets", default=str(HERE / "tickets" / "click-bitrot.json"))
    ap.add_argument("--conditions", default="none,memory")
    ap.add_argument("--action-model", required=True)
    ap.add_argument("--memory-model", default="")
    ap.add_argument("--api-base", default="")
    ap.add_argument("--session-usd-cap", type=float, default=5.0)
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--keep-dir", required=True)
    ap.add_argument("--out", default="evals/report/repeat.json")
    args = ap.parse_args()
    args.memory_model = args.memory_model or args.action_model

    spec = json.loads(Path(args.tickets).read_text())
    if not all(is_self_hosted(m) for m in (args.action_model, args.memory_model)):
        print("note: a hosted model is in the mix, this run will be billed per token")
    root = Path(args.keep_dir)
    root.mkdir(parents=True, exist_ok=True)
    print(f"upstream: {spec['repo']}@{spec['ref']}, wall={spec['wall_re']!r}")

    out = []
    for cond in [c.strip() for c in args.conditions.split(",") if c.strip()]:
        print(f"== {cond}")
        r = run_condition(cond, args, spec, root)
        w = r["waste"]
        print(
            f"  {cond}: wall_hits={w['wall_hits']} recovered={w['recovered']} "
            f"turns_wall_to_green={w['turns_wall_to_green']} reminders={r['reminders_total']}"
        )
        out.append(r)

    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"\nreport: {args.out}")
    if len(out) == 2 and not any(r["waste"]["wall_hit"] for r in out):
        print("neither arm hit the wall: the ticket never brought it back, so this")
        print("run measured nothing. Fix the ticket, not the numbers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
