"""Live LongDebug-Causal runner: a real agent works each task's sessions in Docker, with or without memory."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "packages" / "agentmem" / "src"))
sys.path.insert(0, str(HERE.parents[1] / "evals" / "src"))

import judge_prompts as J  # noqa: E402
import smoke as SM  # noqa: E402
from agentmem.config import AgentMemConfig  # noqa: E402
from agentmem.llm.anthropic import AnthropicProvider  # noqa: E402
from agentmem.session import MemorySession  # noqa: E402
from agentmem.triggers import default as default_trigger  # noqa: E402
from agentmem_evals.tbench.loop import ActionLoop, CountingProvider  # noqa: E402

SESSION_TURN_CAP = 15  # per the benchmark spec


@dataclass
class SessionOutcome:
    name: str
    visible_pass: bool
    hidden_output: str
    diff: str
    turns: int
    usd: float
    reminders: int
    stop_reason: str


@dataclass
class TaskOutcome:
    task_id: str
    condition: str
    sessions: list[SessionOutcome] = field(default_factory=list)
    wrapup_answer: str = ""
    root_cause: dict | None = None
    repeat_rate: dict | None = None
    usd: float = 0.0


def _localize(text: str) -> str:
    """The containers run plain pytest; uv isn't installed in them."""
    return text.replace("uv run pytest", "python -m pytest").replace("uv run ", "python ")


def load_sessions(task_dir: Path) -> list[dict]:
    data = yaml.safe_load((task_dir / "sessions.yaml").read_text())
    return [
        {
            "name": s["name"],
            "ticket": _localize(s["ticket"]),
            "visible": _localize(s["visible"]),
        }
        for s in data["sessions"]
    ]


def sh(cmd: list[str], timeout: int = 600) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


class Container:
    """One task container over a bind-mounted workdir; commands run inside,
    diffs are taken host-side with a private git overlay."""

    def __init__(self, tid: str, task_dir: Path, workdir: Path) -> None:
        self.tid = tid
        self.task_dir = task_dir
        self.workdir = workdir
        self.name = f"agentmem-ct-{tid.lower()}-{os.getpid()}"
        self.image = f"agentmem-ct-{tid.lower()}"
        self.container_wd = "/work"

    def up(self) -> None:
        code, out = sh(["docker", "build", "-t", self.image, str(self.task_dir)])
        if code != 0:
            raise RuntimeError(f"docker build failed for {self.tid}:\n{out[-800:]}")
        code, out = sh(
            ["docker", "image", "inspect", self.image, "--format", "{{.Config.WorkingDir}}"]
        )
        wd = out.strip()
        if code == 0 and wd:
            self.container_wd = wd
        sh(["docker", "rm", "-f", self.name])
        code, out = sh(
            [
                "docker",
                "run",
                "-d",
                "--name",
                self.name,
                "-v",
                f"{self.workdir}:{self.container_wd}",
                "-v",
                f"{self.task_dir / 'verifier'}:/verifier:ro",
                self.image,
                "sleep",
                "infinity",
            ]
        )
        if code != 0:
            raise RuntimeError(f"docker run failed for {self.tid}:\n{out[-800:]}")
        subprocess.run(["git", "init", "-q"], cwd=self.workdir, capture_output=True, text=True)
        subprocess.run(["git", "add", "-A"], cwd=self.workdir, capture_output=True, text=True)
        subprocess.run(
            ["git", "-c", "user.email=e@x", "-c", "user.name=eval", "commit", "-qm", "s0"],
            cwd=self.workdir,
            capture_output=True,
            text=True,
        )

    def exec(self, command: str, timeout: int = 120) -> tuple[int, str]:
        return sh(
            ["docker", "exec", "-w", self.container_wd, self.name, "bash", "-lc", command],
            timeout=timeout,
        )

    def hidden(self) -> str:
        cmd = SM.TASKS[self.tid].hidden.format(V="/verifier", W=self.container_wd)
        _, out = self.exec(cmd, timeout=300)
        return out

    def diff_and_commit(self, label: str) -> str:
        subprocess.run(["git", "add", "-A"], cwd=self.workdir, capture_output=True)
        p = subprocess.run(
            ["git", "diff", "--cached", "HEAD"],
            cwd=self.workdir,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                "git",
                "-c",
                "user.email=e@x",
                "-c",
                "user.name=eval",
                "commit",
                "-qm",
                label,
                "--allow-empty",
            ],
            cwd=self.workdir,
            capture_output=True,
        )
        return p.stdout

    def down(self) -> None:
        sh(["docker", "rm", "-f", self.name])


class FakeDoneProvider:
    """Zero-cost stand-in for plumbing checks: every session ends immediately."""

    model = "fake-done"

    def complete(self, *, system, messages, tools=None, max_tokens=1024):
        from agentmem.llm.base import LLMResponse
        from agentmem.schemas import TokenUsage
        from agentmem.tools import ToolCall

        return LLMResponse(
            tool_calls=[ToolCall(name="task_done", args={"summary": "noop"}, block_id="t1")],
            usage=TokenUsage(),
        )


class HaikuJudge:
    def __init__(self, model: str) -> None:
        self._p = CountingProvider(AnthropicProvider(model=model, timeout=120.0))

    def complete(self, prompt: str) -> str:
        return self._p.complete(
            system="You are a strict grader. Follow the prompt exactly.",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1024,
        ).text

    @property
    def usd(self) -> float:
        return self._p.usd


def run_task(
    tid: str,
    condition: str,
    args: argparse.Namespace,
    judge: J.Judge | None,
) -> TaskOutcome:
    task_dir = HERE / SM.task_dir(tid)
    gold = J.load_gold(HERE / "gold" / f"{tid}.yaml")
    sessions = load_sessions(task_dir)

    keep_root = Path(args.keep_dir) if args.keep_dir else None
    tmp = (
        keep_root / f"{tid}-{condition}"
        if keep_root
        else Path(tempfile.mkdtemp(prefix=f"ct-{tid}-{condition}-"))
    )
    workdir = tmp / "repo"
    if workdir.exists():
        raise RuntimeError(f"refusing to reuse {workdir}")
    workdir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["cp", "-R", str(task_dir / "repo"), str(workdir)], check=True)

    box = Container(tid, task_dir, workdir)
    box.up()
    out = TaskOutcome(task_id=tid, condition=condition)
    mem_state = tmp / "mem"
    records: list[J.SessionRecord] = []

    try:
        for i, sess in enumerate(sessions, start=1):
            is_last = i == len(sessions)
            memory = None
            mem_counter = None
            if condition == "memory":
                mem_counter = CountingProvider(
                    AnthropicProvider(model=args.memory_model, timeout=300.0)
                )
                memory = MemorySession(
                    task=f"{tid}: maintain this service across sessions",
                    provider=mem_counter,
                    trigger=default_trigger(),
                    async_worker=False,
                    session_id=f"{tid}-{condition}",
                    config=AgentMemConfig(state_dir=str(mem_state)),
                )

            if is_last:
                out.wrapup_answer = _wrapup(args, gold, memory)

            action = CountingProvider(AnthropicProvider(model=args.action_model, timeout=300.0))
            instruction = (
                f"You maintain the project in {box.container_wd} (a Python service). "
                f"Work this ticket, keep changes minimal, and finish with task_done.\n\n"
                f"Ticket: {sess['ticket']}"
            )
            loop = ActionLoop(
                action,
                instruction,
                memory=memory,
                extra_cost=(lambda mc=mem_counter: mc.usd) if mem_counter else None,
                max_turns=SESSION_TURN_CAP,
                usd_cap=args.session_usd_cap,
                max_tokens=args.max_tokens,
            )
            while True:
                d = loop.next_decision()
                if d.kind != "exec":
                    break
                code, output = box.exec(d.command, timeout=120)
                loop.record_exec(d, output, "", code)

            vis_code, vis_out = box.exec(sess["visible"], timeout=300)
            hidden_out = box.hidden()
            diff = box.diff_and_commit(sess["name"])
            if memory is not None:
                memory.observe(
                    {
                        "kind": "tool_result",
                        "tool_name": "session_tests",
                        "ok": vis_code == 0,
                        "text": f"end of {sess['name']}: visible tests "
                        f"{'passed' if vis_code == 0 else 'FAILED'}\n{vis_out[-800:]}",
                    }
                )
                memory.close(task_reward=1.0 if vis_code == 0 else 0.0)

            mem_usd = mem_counter.usd if mem_counter else 0.0
            out.sessions.append(
                SessionOutcome(
                    name=sess["name"],
                    visible_pass=vis_code == 0,
                    hidden_output=hidden_out[-4000:],
                    diff=diff[:8000],
                    turns=loop.turns,
                    usd=round(loop.spent_usd + mem_usd, 4),
                    reminders=loop.reminders_injected,
                    stop_reason=loop.stop_reason,
                )
            )
            out.usd += loop.spent_usd + mem_usd
            records.append(J.SessionRecord(session=i, diff=diff, hidden_output=hidden_out))
            print(
                f"  {tid}/{condition} {sess['name']}: turns={loop.turns} "
                f"visible={'ok' if vis_code == 0 else 'FAIL'} ${out.usd:.2f}",
                flush=True,
            )
    finally:
        box.down()

    rate = J.repeated_cause_rate(records, gold)
    out.repeat_rate = {
        "opportunities": rate.opportunities,
        "recurrences": rate.recurrences,
        "rate": rate.rate,
    }
    if judge is not None:
        diff_summary = "\n".join(r.diff for r in records)[-6000:]
        rc = J.score_root_cause(gold, out.wrapup_answer, diff_summary, judge)
        out.root_cause = {
            "keyword_passed": rc.keyword_passed,
            "judge_score": rc.judge_score,
            "identified": rc.identified,
        }
    return out


def _wrapup(args: argparse.Namespace, gold: J.GoldSpec, memory: MemorySession | None) -> str:
    """The spec's probe, asked before the final ticket; memory answers from its bank."""
    if args.fake_action:
        return "(fake action provider, no probe)"
    ctx = ""
    if memory is not None:
        digest = memory.bank.render_full()
        project = memory.project_bank.render_full()
        ctx = f"Notes you keep about this project:\n{project}\n{digest}\n\n"
    provider = AnthropicProvider(model=args.action_model, timeout=300.0)
    return provider.complete(
        system="You are the engineer who worked the previous sessions on this project.",
        messages=[
            {
                "role": "user",
                "content": f"{ctx}{gold.wrapup_question}\nAnswer in 2-3 sentences.",
            }
        ],
        max_tokens=2048,
    ).text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tasks", default="CT-01,CT-03,CT-05")
    ap.add_argument("--conditions", default="none,memory")
    ap.add_argument("--action-model", default="claude-sonnet-5")
    ap.add_argument("--memory-model", default="claude-haiku-4-5")
    ap.add_argument("--judge-model", default="claude-haiku-4-5")
    ap.add_argument("--session-usd-cap", type=float, default=0.20)
    ap.add_argument("--run-usd-cap", type=float, required=True)
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--fake-action", action="store_true", help="free plumbing check")
    ap.add_argument("--keep-dir", default=None)
    ap.add_argument("--out", default=None, help="report json path")
    args = ap.parse_args()

    tasks = [t.strip() for t in args.tasks.split(",") if t.strip()]
    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    n_sessions = sum(len(load_sessions(HERE / SM.task_dir(t))) for t in tasks)
    worst = n_sessions * len(conditions) * args.session_usd_cap
    print(f"worst-case spend: ${worst:.2f} (cap ${args.run_usd_cap:.2f})")
    if worst > args.run_usd_cap:
        sys.exit("worst-case exceeds --run-usd-cap")
    if not os.environ.get("ANTHROPIC_API_KEY") and not args.fake_action:
        sys.exit("ANTHROPIC_API_KEY is not set")

    judge = None if args.no_judge else HaikuJudge(args.judge_model)
    results = []
    for tid in tasks:
        for cond in conditions:
            print(f"== {tid} / {cond}", flush=True)
            results.append(run_task(tid, cond, args, judge))

    print(f"\n{'task':8} {'condition':9} {'root_cause':>10} {'repeat_rate':>11} {'usd':>6}")
    for r in results:
        rc = "-" if r.root_cause is None else ("YES" if r.root_cause["identified"] else "no")
        rate = None if r.repeat_rate is None else r.repeat_rate["rate"]
        rr = "-" if rate is None else f"{rate:.2f}"
        print(f"{r.task_id:8} {r.condition:9} {rc:>10} {rr:>11} {r.usd:>6.2f}")
    total = sum(r.usd for r in results) + (judge.usd if judge else 0.0)
    print(f"total spend including judge: ${total:.2f}")

    out_path = Path(args.out or f"evals/report/causal-live-{time.strftime('%m%d-%H%M%S')}.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            **{k: v for k, v in r.__dict__.items() if k != "sessions"},
            "sessions": [s.__dict__ for s in r.sessions],
        }
        for r in results
    ]
    out_path.write_text(json.dumps(payload, indent=2))
    print(f"report: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
