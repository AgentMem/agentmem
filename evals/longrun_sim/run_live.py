"""LongRun-sim live runner: a capabilities dashboard for AgentMem's differentiators."""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
import metrics as M  # noqa: E402
import scenario as S  # noqa: E402
from agentmem import MemorySession, triggers  # noqa: E402
from agentmem.config import AgentMemConfig  # noqa: E402
from agentmem.integrations.claude_code import bank_digest  # noqa: E402
from agentmem.llm.base import LLMResponse  # noqa: E402
from agentmem.schemas import Event, TokenUsage  # noqa: E402
from agentmem.tools import SAVE_PROCEDURAL, ToolCall  # noqa: E402

TRAP_APPEARANCE = 5  # the session where each repo's known failure recurs

# What each repo's sessions surface: hard requirements, then the lesson from its main
# failure (with the ruled-out lead and the root cause), then a recurrence.
REPO_CONTENT = {
    "a": {
        "req": "Hard requirement for repo A (HTTP service): the public API signatures in "
        "api.py are frozen and must never change; all request timeouts must come from "
        "config.py, never hardcoded at the call site.",
        "lesson": "Fixed the token-expiry test failures in repo A. Ruled out the call site "
        "in make_token; the real root cause was DEFAULT_TTL in config.py, and raising it fixed it.",
        "trap": "The token-expiry test in repo A is failing again.",
    },
    "b": {
        "req": "Hard requirement for repo B (data pipeline): cache keys must include the "
        "normalize.py version, and city and country names must be casefolded.",
        "lesson": "The nightly aggregate numbers went wrong for some cities in repo B. Ruled "
        "out the database; the cause was a stale cache whose keys were missing the normalize version.",
        "trap": "Some repo B cities show wrong nightly totals again.",
    },
    "c": {
        "req": "Hard requirement for repo C (async worker): the job queue is serialized by "
        "one shared asyncio lock; httpx stays pinned and the client uses proxies=, not "
        "proxy=; retries are bounded by RETRIES.",
        "lesson": "Fixed a repo C job-queue race with a single shared asyncio lock. Ruled out "
        "adding threads; a later httpx upgrade broke it because proxy= replaced proxies=.",
        "trap": "Repo C jobs are racing on the queue again.",
    },
}


def events_for(repo: str, appearance: int) -> list[Event]:
    c = REPO_CONTENT[repo]
    if appearance == 0:
        return [Event(kind="message", role="user", text=c["req"])]
    if appearance == 1:
        return [
            Event(kind="message", role="assistant", text=c["lesson"]),
            Event(
                kind="tool_result", tool_name="pytest", ok=True, text="tests green after the fix"
            ),
        ]
    if appearance == TRAP_APPEARANCE:
        return [
            Event(kind="message", role="user", text=c["trap"]),
            Event(
                kind="tool_result",
                tool_name="pytest",
                ok=False,
                text="FAILED (same symptom as before)",
            ),
        ]
    return [
        Event(
            kind="message",
            role="user",
            text=f"Routine work on repo {repo.upper()} (touch {appearance}).",
        )
    ]


def grade(answer: str, probe: S.Probe) -> bool:
    low = answer.lower()
    return all(t.lower() in low for t in probe.answer_contains) and not any(
        f.lower() in low for f in probe.forbidden
    )


class _Fake:
    """Offline stand-in: Phase 1 saves a typed entry, everything else echoes."""

    model = "fake"
    _n = 0

    def complete(
        self, *, system: str, messages: list, tools: list | None = None, max_tokens: int = 1024
    ) -> LLMResponse:
        if tools:
            _Fake._n += 1
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        name=SAVE_PROCEDURAL,
                        args={"tag": "fix", "content": "a lesson"},
                        block_id=f"t{_Fake._n}",
                    )
                ],
                usage=TokenUsage(input_tokens=50, output_tokens=10),
            )
        return LLMResponse(
            text="<context_for_action>\n- recall the prior fix (P-001)\n</context_for_action>",
            usage=TokenUsage(input_tokens=40, output_tokens=8),
        )


# List prices per Mtok (in, out), matched by id prefix so the --max-usd cap is honest on
# any model. Unknown models assume Opus prices, erring toward stopping early. Verify
# actual spend on the billing page (Sonnet 5 has an intro discount through 2026-08).
_PRICES = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-opus-4-8": (5.0, 25.0),
}
_DEFAULT_PRICE = (5.0, 25.0)


class Counting:
    """Wrap the provider to sum tokens across every call and estimate cost."""

    def __init__(self, model: str, dry_run: bool) -> None:
        if dry_run:
            self.inner: object = _Fake()
        else:
            from agentmem.llm.anthropic import AnthropicProvider

            self.inner = AnthropicProvider(model=model)
        self.model = model
        self.tin = self.tout = self.calls = 0
        self.price = next(
            (p for prefix, p in _PRICES.items() if model.startswith(prefix)), _DEFAULT_PRICE
        )

    def complete(self, **kw: object) -> LLMResponse:
        r = self.inner.complete(**kw)  # type: ignore[attr-defined]
        self.tin += r.usage.input_tokens
        self.tout += r.usage.output_tokens
        self.calls += 1
        return r

    @property
    def cost(self) -> float:
        return self.tin / 1e6 * self.price[0] + self.tout / 1e6 * self.price[1]


def _config(state_dir: str) -> AgentMemConfig:
    return AgentMemConfig(
        state_dir=state_dir,
        max_tool_rounds=2,  # a second round lets Phase 1 add causal links
        advantage_enabled=True,  # learned policy on
        advantage_gate=True,  # let it gate (a learned-to-stay-silent signal)
        # Sonnet-tier models run adaptive thinking by default, which spends from the
        # same output budget; the default 1024 would truncate tool calls mid-step.
        max_output_tokens=4096,
    )


def _ask(provider: Counting, question: str, memory: str | None) -> str:
    ctx = f"Project notes you remember:\n{memory}\n\n" if memory else ""
    return provider.complete(
        system="You answer questions about projects you have worked on. If you do not know, say so.",
        messages=[
            {"role": "user", "content": f"{ctx}Question: {question}\nAnswer in one sentence."}
        ],
        max_tokens=1024,  # room for adaptive thinking ahead of the one-sentence answer
    ).text


def run(model: str, max_usd: float, dry_run: bool, keep_state: str | None = None) -> dict:
    provider = Counting(model, dry_run)
    # A kept state dir means the policy DB survives for offline analysis (AUC).
    holder = (
        tempfile.TemporaryDirectory(prefix="agentmem-longrun-")
        if keep_state is None
        else contextlib.nullcontext(keep_state)
    )
    with holder as tmp:
        Path(tmp).mkdir(parents=True, exist_ok=True)
        state_dir = f"{tmp}/mem"
        tele = Path(state_dir) / "telemetry.jsonl"
        created_repo: dict[str, str] = {}
        rows: list[dict] = []
        read = 0
        records: list[M.SessionRecord] = []
        seen = dict.fromkeys(S.REPOS, 0)

        for sched in S.schedule():
            repo, appearance = sched.repo, seen[sched.repo]
            mem = MemorySession(
                task="Maintain three projects across many sessions",
                provider=provider,
                trigger=triggers.default(),
                async_worker=False,
                session_id="longrun",
                config=_config(state_dir),
            )
            mem.observe(events_for(repo, appearance))
            bank_size = len(mem.bank.all_entries())
            mem.close(task_reward=0.0)
            seen[repo] += 1

            new = []
            if tele.exists():
                lines = tele.read_text().splitlines()
                for ln in lines[read:]:
                    try:
                        row = json.loads(ln)
                    except json.JSONDecodeError:
                        continue
                    row["_repo"], row["_trap"] = repo, appearance == TRAP_APPEARANCE
                    for tc in row.get("tool_calls", []):
                        for effect, val in tc.items():
                            if effect == "created" and isinstance(val, str):
                                created_repo[val] = repo
                    new.append(row)
                read = len(lines)
            rows.extend(new)

            cited = [created_repo.get(i, repo) for r in new for i in r.get("cited_ids", [])]
            records.append(
                M.SessionRecord(
                    repo=repo,
                    index=sched.index,
                    passed=False,
                    repeated_failures=0,
                    bank_size=bank_size,
                    cited_repos=cited,
                )
            )
            if provider.cost > max_usd:
                print(
                    f"[budget] stopping at session {sched.index}, ~${provider.cost:.2f}", flush=True
                )
                break

        final = MemorySession(
            task="inspect", provider=provider, session_id="longrun", config=_config(state_dir)
        )
        entries, edges = final.bank.all_entries(), final.bank.edges
        # Same recall surface production uses at SessionStart: project tier included.
        digest = bank_digest(final.bank, project=final.project_bank) or ""
        mem_probes, base_probes, probe_rows = [], [], []
        for probe in S.all_probes():
            # Separate the two failure modes: fact absent from the digest is a memory
            # problem; fact present but the graded answer missing it is an answer or
            # grading problem. Without this split a miss is undiagnosable.
            in_digest = all(t.lower() in digest.lower() for t in probe.answer_contains)
            answer = _ask(provider, probe.question, digest)
            mem_ok = grade(answer, probe)
            base_ok = grade(_ask(provider, probe.question, None), probe)
            mem_probes.append(M.ProbeResult(probe.repo, 30, mem_ok))
            base_probes.append(M.ProbeResult(probe.repo, 30, base_ok))
            probe_rows.append(
                {
                    "id": probe.id,
                    "in_digest": in_digest,
                    "mem_ok": mem_ok,
                    "base_ok": base_ok,
                    "answer": " ".join(answer.split())[:80],
                }
            )

    injects = [r for r in rows if r.get("decision") == "inject"]
    return {
        "entries": entries,
        "edges": edges,
        "injects": injects,
        "rows": rows,
        "records": records,
        "mem_probes": mem_probes,
        "base_probes": base_probes,
        "probe_rows": probe_rows,
        "provider": provider,
    }


def report(res: dict) -> str:
    entries, edges, injects, rows, records = (
        res["entries"],
        res["edges"],
        res["injects"],
        res["rows"],
        res["records"],
    )
    provider = res["provider"]
    kinds = Counter(e.kind for e in entries)
    ptags = Counter(e.tag for e in entries if e.kind == "procedural")
    erels = Counter(e.rel for e in edges)
    trap_injects = sum(1 for r in injects if r.get("_trap"))
    adv_rows = sum(1 for r in rows if "advantage" in r)
    gated = sum(1 for r in rows if r.get("gate_applied"))

    lines = [
        "# LongRun-sim capabilities dashboard",
        "",
        f"Model `{provider.model}` · {len(records)} sessions · est ~${provider.cost:.3f} "
        f"({provider.calls} calls, {provider.tin} in / {provider.tout} out)",
        "",
        "## The four differentiators",
        f"1. **Structured procedural memory**: {len(entries)} entries {dict(kinds)}; "
        f"procedural tags {dict(ptags) or '(none)'}.",
        f"2. **Causal memory**: {len(edges)} edges {dict(erels) or '(none)'}.",
        f"3. **Proactive intervention**: {len(injects)} injects over {len(rows)} steps; "
        f"{trap_injects} on recurring-failure sessions, {len(injects) - trap_injects} on routine.",
        f"4. **Learned policy (advantage)**: {adv_rows} steps carried an advantage estimate, "
        f"{gated} gated to silence.",
        "",
        "## Long-horizon numbers",
        "",
        "| Metric | Result | Bar |",
        "|---|---|---|",
        f"| Retention (no-memory baseline) | {M.retention_rate(res['base_probes']):.0%} | - |",
        f"| Retention (AgentMem) | {M.retention_rate(res['mem_probes']):.0%} | ≥ {M.RETENTION_MIN:.0%} |",
        f"| Interference (cross-repo) | {M.interference_rate(records):.1%} | < {M.INTERFERENCE_MAX:.0%} |",
        f"| Bank-growth ratio | {M.bank_growth_ratio(records):.2f} | < {M.BANK_GROWTH_MAX} |",
        "",
        "Interference is measured on one shared bank across all three repos (the hard case); "
        "in production AgentMem scopes memory per project, so cross-repo citation is structurally "
        "near zero.",
        "",
        "## Per-probe detail",
        "",
        "| Probe | Fact in digest | With memory | No memory | Answer (with memory) |",
        "|---|---|---|---|---|",
    ]
    for p in res["probe_rows"]:
        lines.append(
            f"| {p['id']} | {'yes' if p['in_digest'] else 'NO'} | "
            f"{'ok' if p['mem_ok'] else 'miss'} | {'ok' if p['base_ok'] else 'miss'} | "
            f"{p['answer']} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", default="claude-haiku-4-5", help="memory + probe model")
    ap.add_argument("--max-usd", type=float, default=1.0, help="hard spend cap")
    ap.add_argument(
        "--dry-run", action="store_true", help="offline plumbing check, no key, no cost"
    )
    ap.add_argument("--out", default="evals/report/longrun", help="report directory")
    ap.add_argument(
        "--keep-state", default=None, help="keep session state here instead of a tempdir"
    )
    args = ap.parse_args(argv)

    res = run(args.model, args.max_usd, args.dry_run, args.keep_state)
    md = report(res)
    print("\n" + md)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "REPORT.md").write_text(md + "\n")
    print(f"\nReport written to {out / 'REPORT.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
