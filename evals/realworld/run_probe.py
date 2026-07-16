#!/usr/bin/env python3
"""Ask an agent what it did to a real upstream repo, after its context is gone."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "packages" / "agentmem" / "src"))
sys.path.insert(0, str(HERE.parents[1] / "evals" / "src"))
sys.path.insert(0, str(HERE.parents[0] / "longdebug_causal"))

import grounding as G  # noqa: E402
from agentmem.config import AgentMemConfig  # noqa: E402
from agentmem.session import MemorySession  # noqa: E402
from agentmem.triggers import default as default_trigger  # noqa: E402
from agentmem_evals.tbench.loop import ActionLoop, CountingProvider, is_self_hosted  # noqa: E402

# The tickets live in a per-repo spec file, not here. They have to name something the
# repo actually has, so they cannot be shared, but nothing about their shape is tuned
# to a result: run the suite, find a decision point, add a test, run it again. Ordinary
# maintenance chores on somebody else's code. See tickets/*.json.
PROBE = (
    "Before the next ticket: in 2-3 sentences, what did you work on in this project "
    "across the earlier sessions, and did anything fail along the way? Be specific "
    "about files."
)

TURN_CAP = 12


def sh(cmd: list[str], timeout: int = 900) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


class Box:
    """A container holding a real upstream checkout, nothing of ours inside it."""

    def __init__(self, repo_url: str, ref: str, workdir: Path, test_deps: str = "") -> None:
        # uuid, not a timestamp: two seeds launched in the same second collided on
        # the container name and the second one died before it ran anything.
        self.name = f"agentmem-rw-{uuid.uuid4().hex[:12]}"
        self.workdir = workdir
        self.repo_url = repo_url
        self.ref = ref
        self.test_deps = test_deps
        self.wd = "/work"

    def up(self) -> None:
        code, out = sh(["git", "clone", "-q", self.repo_url, str(self.workdir)])
        if code != 0:
            raise RuntimeError(f"clone failed: {out[-400:]}")
        sh(["git", "-C", str(self.workdir), "checkout", "-q", self.ref])
        df = self.workdir / "Dockerfile.agentmem"
        deps = f"pytest {self.test_deps}".strip()
        # git, because a project that versions itself from its tags cannot report a
        # version without it, and pip then fails on metadata rather than on the code.
        df.write_text(
            "FROM python:3.11-slim\n"
            "RUN apt-get update && apt-get install -y --no-install-recommends git "
            "&& rm -rf /var/lib/apt/lists/*\n"
            "WORKDIR /work\nCOPY . /work\n"
            "RUN git config --global --add safe.directory /work\n"
            f"RUN pip install --no-cache-dir -q -e . {deps} || "
            f"pip install --no-cache-dir -q . {deps}\n"
        )
        code, out = sh(["docker", "build", "-q", "-f", str(df), "-t", self.name, str(self.workdir)])
        if code != 0:
            raise RuntimeError(f"build failed: {out[-600:]}")
        code, out = sh(
            [
                "docker",
                "run",
                "-d",
                "--name",
                self.name,
                "-v",
                f"{self.workdir}:{self.wd}",
                self.name,
                "sleep",
                "infinity",
            ]
        )
        if code != 0:
            raise RuntimeError(f"run failed: {out[-400:]}")

    def exec(self, command: str, timeout: int = 120) -> tuple[int, str]:
        return sh(["docker", "exec", "-w", self.wd, self.name, "bash", "-lc", command], timeout)

    def down(self) -> None:
        sh(["docker", "rm", "-f", self.name])


def build_provider(model: str, api_base: str):  # noqa: ANN201
    if model.startswith("litellm/"):
        from agentmem.llm.litellm import LiteLLMProvider

        return LiteLLMProvider(
            model=model.removeprefix("litellm/"),
            api_base=api_base or None,
            timeout=300.0,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
    from agentmem.llm.anthropic import AnthropicProvider

    return AnthropicProvider(model=model, timeout=300.0)


def run_condition(cond: str, args: argparse.Namespace, root: Path) -> dict:
    workdir = root / f"repo-{cond}"
    box = Box(args.repo, args.ref, workdir, args.test_deps)
    box.up()
    mem_state = root / f"mem-{cond}"
    sessions_log, probe = [], ""
    try:
        for i, ticket in enumerate(args.sessions, start=1):
            memory = None
            if cond == "memory":
                memory = MemorySession(
                    task="Maintain this project across sessions",
                    provider=CountingProvider(build_provider(args.memory_model, args.api_base)),
                    trigger=default_trigger(),
                    async_worker=False,
                    session_id=f"rw-{cond}",
                    config=AgentMemConfig(
                        state_dir=str(mem_state), advantage_enabled=True, advantage_gate=False
                    ),
                )
            if i == len(args.sessions):
                probe = ask_probe(args, memory)

            loop = ActionLoop(
                CountingProvider(build_provider(args.action_model, args.api_base)),
                f"You maintain the project in /work. Work this ticket, then task_done.\n\n"
                f"Ticket: {ticket}",
                memory=memory,
                max_turns=TURN_CAP,
                usd_cap=args.session_usd_cap,
                max_tokens=args.max_tokens,
            )
            while True:
                d = loop.next_decision()
                if d.kind != "exec":
                    break
                code, out = box.exec(d.command)
                loop.record_exec(d, out, "", code)
            if memory is not None:
                memory.close(task_reward=0.0)
            sessions_log.append(
                {
                    "ticket": ticket[:60],
                    "turns": loop.turns,
                    "stop": loop.stop_reason,
                    "spent_usd": round(loop.spent_usd, 4),
                }
            )
            print(f"  {cond} s{i}: turns={loop.turns} {loop.stop_reason}", flush=True)
    finally:
        box.down()
    return {
        "condition": cond,
        "sessions": sessions_log,
        "probe_answer": probe,
        "repo": str(workdir),
    }


def ask_probe(args: argparse.Namespace, memory: MemorySession | None) -> str:
    ctx = ""
    if memory is not None:
        ctx = (
            f"Notes you keep about this project:\n{memory.project_bank.render_full()}\n"
            f"{memory.bank.render_full()}\n\n"
        )
    provider = build_provider(args.action_model, args.api_base)
    return provider.complete(
        system="You are the engineer who worked the earlier sessions on this project.",
        messages=[{"role": "user", "content": f"{ctx}{PROBE}"}],
        max_tokens=2048,
    ).text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tickets", default=str(HERE / "tickets" / "click.json"))
    ap.add_argument("--repo", default="", help="overrides the tickets file")
    ap.add_argument("--ref", default="")
    ap.add_argument("--test-deps", default="", help="extra pip packages the suite needs")
    ap.add_argument("--conditions", default="none,memory")
    ap.add_argument("--action-model", required=True)
    ap.add_argument("--memory-model", default="")
    ap.add_argument("--api-base", default="")
    ap.add_argument("--session-usd-cap", type=float, default=5.0)
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--keep-dir", required=True)
    ap.add_argument("--out", default="evals/report/realworld-probe.json")
    args = ap.parse_args()
    args.memory_model = args.memory_model or args.action_model

    spec = json.loads(Path(args.tickets).read_text())
    args.sessions = spec["sessions"]
    args.repo = args.repo or spec["repo"]
    args.ref = args.ref or spec["ref"]
    args.test_deps = args.test_deps or spec.get("test_deps", "")

    if not all(is_self_hosted(m) for m in (args.action_model, args.memory_model)):
        print("note: a hosted model is in the mix, this run will be billed per token")

    root = Path(args.keep_dir)
    root.mkdir(parents=True, exist_ok=True)
    print(f"upstream: {args.repo}@{args.ref} (not ours, no gold answer, no planted trap)")
    print(f"tickets:  {Path(args.tickets).name} ({len(args.sessions)} sessions)")

    out = []
    for cond in [c.strip() for c in args.conditions.split(",") if c.strip()]:
        print(f"== {cond}")
        out.append(run_condition(cond, args, root))

    print(f"\n{'condition':10} {'grounded':>9}  cited from the real repo")
    for r in out:
        gr = G.score(r["probe_answer"], Path(r["repo"]))
        r["grounding"] = {k: v for k, v in gr.items() if k != "invented"}
        r["invented"] = gr["invented"]
        print(f"{r['condition']:10} {('YES' if gr['grounded'] else 'no'):>9}  {gr['real'][:5]}")
        print(f"           answer: {(r['probe_answer'] or '')[:150]}")

    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"\nreport: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
