<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/brand/lockup-white.svg">
  <img alt="AgentMem" src="assets/brand/lockup-ink.svg" width="380">
</picture>

**Verifiable memory for AI agents.**

*Know what your agent actually did, and prove it's true.*

Runs alongside Claude Code, Cursor, Aider, the Claude Agent SDK, LangGraph, the OpenAI
Agents SDK, or your own loop, without changing how they work.

[![CI](https://github.com/agentmem/agentmem/actions/workflows/ci.yml/badge.svg)](https://github.com/agentmem/agentmem/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](./LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)

</div>

---

## The problem

Ask an agent what it just did, and you cannot trust the answer. A weaker model invents a
confident, detailed account of work it never performed, naming files that do not exist. A
stronger one, once its context is compacted or the session resets, just says it does not
remember. The two are told in the same steady, competent register, so nothing in the tone
tells you which is real, and neither is something you can hand off, build on, or audit.

Storage-style memory, the write-everything-and-retrieve-on-similarity kind, does not fix
this. It recalls what the agent *said*, not what actually *happened*. A record you can
trust has to be checked against reality, not taken on the agent's word.

## What AgentMem does

AgentMem keeps a record of what the agent did that is grounded in what actually changed,
your files and your git history, and it treats the agent as an untrusted witness.

1. **Record, out of band.** As the agent works, its actions and their real effects are
   captured at the tool boundary, never scraped from what the agent says about itself.
2. **Verify against ground truth.** Every claim is checked against the repository and
   git, which decide. The model never grades itself; anything the record cannot confirm
   is flagged, not quietly accepted.
3. **Surface it when it matters.** After a compaction, on a new session, or when you ask,
   the verified record is handed back, grounded and selective, so the thread survives and
   the account is true. Most of the time it stays silent.

## See what it caught

The record is a command. Give `agentmem report` what an agent said it did and a checkout,
and it verifies the account against the repository, treating the agent as an untrusted
witness: a file it claims to have touched is confirmed only if the file actually exists.

```bash
agentmem report --account "$(cat what-the-agent-said.txt)" --repo .
```

On a real run from this project's own evals ([pallets/click](evals/realworld/RESULTS.md)),
the agent without memory named four files that do not exist in the library; with memory it
named five that do, every one confirmed against git. A fully fabricated account exits
non-zero, so a script or a CI step can gate on the agent not inventing its own past.

> AgentMem never edits the action agent's system prompt, tools, or decoding. Reminders are
> **transient**: injected once, consumed once, never baked into base instructions.

## Where this is going

Today AgentMem is a flight recorder for one agent: an honest, verifiable memory of what it
did across long and multi-session work. The same record is built to be shared. When several
agents, or agents and people, work together, they read one verified account of who did
what, and trust it because it is checked against reality rather than taken on each other's
word. Memory stops being a booster for a single agent's thinking and becomes the source of
truth a system of agents coordinates on. That is the substrate autonomous work will need,
and where AgentMem is headed.

## Quickstart

```bash
pip install agentmem-core   # or: uv add agentmem-core (import path stays `agentmem`)
agentmem demo               # offline, no key needed: watch memory stop a repeated failure

export ANTHROPIC_API_KEY=sk-ant-...   # then point it at your own agent (see below)
```

Prefer a different backend? The memory agent runs on anything litellm supports. For a free
Gemini key, `pip install 'agentmem-core[litellm]'`, set `GEMINI_API_KEY`, and use
`model="litellm/gemini/gemini-2.5-flash"`.

Wrap your own loop in five lines:

```python
from agentmem import MemorySession, triggers

mem = MemorySession(
    task="Fix the failing auth tests without changing the public API",
    model="claude-haiku-4-5",
    store="sqlite:///.agentmem/run.db",
    trigger=triggers.default(),          # every 3 turns + on tool failure
)

while not done:
    reminder = mem.pending_context()     # str | None, O(1), just reads a cache
    reply = call_your_agent(messages, memory_context=reminder)
    mem.observe(reply.new_messages)      # non-blocking; runs a memory-step if a trigger fires
```

## Integrations

Every integration sits on the same public API and leaves the action agent's prompt, tools, and
decoding untouched. What differs is how the reminder gets in, which is dictated by what the host
allows.

| Host | Install | How memory arrives |
|---|---|---|
| **Claude Code** | `agentmem init claude-code` | Proactive, via hooks (no daemon) |
| **Claude Agent SDK** | `pip install 'agentmem-core[agent-sdk]'` | Proactive, a PostToolUse hook |
| **LangGraph** | built in | Proactive, a graph node |
| **Aider** | `pip install 'agentmem-core[aider]'` | Proactive, drives the coder loop |
| **OpenAI Agents SDK** | `pip install 'agentmem-core[openai-agents]'` | Proactive, run hooks + input filter |
| **Your own loop** | built in | Proactive, `wrap()` or two calls |
| **Cursor, Copilot, Codex, Gemini, and more** | `pip install 'agentmem-core[mcp]'` | On demand via MCP, plus a `checkpoint` nudge |

**Proactive** hosts get the full two-phase behavior: AgentMem decides *when* to speak and pushes a
transient, once-consumed reminder into the next turn. The OpenAI Agents SDK, for example, wires in
through the SDK's own hooks and input filter, so your Agent and its tools are unchanged:

```python
from agents import Runner
from agentmem.integrations.openai_agents import attach_memory

mem = attach_memory(task="Fix the failing auth tests without changing the public API")
result = await Runner.run(
    agent, "start on the ticket",
    context=mem.context, hooks=mem.hooks, run_config=mem.run_config,
)
```

Aider, in a few lines, injecting a reminder before each turn and learning from the edits and test
results after:

```python
from aider.models import Model
from aider.io import InputOutput
from agentmem.integrations.aider import attach_memory

mem = attach_memory(Model("claude-3-7-sonnet"), InputOutput(yes=True),
                    task="Fix the failing auth tests", fnames=["app.py"])
mem.run("the token expiry test is red, take a look")
```

**MCP** hosts (Cursor, GitHub Copilot, Codex CLI, Gemini CLI, Continue, Windsurf) can't be handed a
reminder mid-turn, so there AgentMem is a *pull* surface: a small server exposing `recap`, `search`,
`bank`, and a `checkpoint` tool. `checkpoint` is the closest thing to proactive that portable MCP
allows: the server's own instructions tell the agent to call it before an edit or right after a
failure, and it answers with the same silence-gated, id-cited Phase-2 decision, computed on demand
against the project's salient memory, rather than a raw list of matches.

```bash
pip install 'agentmem-core[mcp]'
claude mcp add --scope project agentmem -- agentmem-mcp   # or add to .cursor/mcp.json, .vscode/mcp.json, ...
codex mcp add agentmem -- agentmem-mcp                    # Codex CLI (writes ~/.codex/config.toml)
```

There is no dedicated Codex adapter yet because Codex doesn't expose lifecycle hooks the way
Claude Code does; the MCP server above is the supported path, and a proactive adapter will follow
if those hooks land.

## How it fits in

<div align="center">
  <img src="assets/architecture.svg" alt="The action agent emits trajectory events to AgentMem, which manages a memory bank (Phase 1), decides whether to intervene (Phase 2), and sends a transient reminder back for the agent's next turn." width="820">
</div>

Two design decisions do most of the work:

- **Async compute, sync inject.** The memory-step (an LLM call) runs on a background worker after
  each event. Hooks and `pending_context()` only ever read a cache, so they return in well under a
  hundred milliseconds and never stall the agent. This is sound because a reminder always applies to
  the *next* turn, so there's time to compute it.
- **The core imports nothing from the integrations.** Claude Code, the Agent SDK, LangGraph, Aider,
  the OpenAI Agents SDK, and the MCP server all sit on top of the same public API, and the LLM
  provider is one adapter (Anthropic by default; a litellm adapter routes the memory agent to
  Gemini, OpenAI, vLLM, or local models).

## Why not just... Mem0 / Letta / a `memory.md` file?

| | Storage-style memory | AgentMem |
|---|---|---|
| Core operation | write + retrieve on similarity | maintain a bank **and decide when to remind** |
| Default behavior | surface matching memories | **stay silent**; intervene only when it changes the next action |
| What's remembered | mostly facts | facts **and** procedural experience (what failed, what fixed it) |
| Grounding | retrieved chunks | every reminder cites a specific entry id, with a cooldown against nagging |

They're complementary: you can point AgentMem's store at a vector DB. The difference is
architectural: retrieval answers *what's relevant*, AgentMem answers *whether to speak now*.

## Measured

LongRun-sim stresses the core claim: one agent maintains three repos over 30 interleaved
sessions, each repo's hard requirements stated early, each repo's known failure resurfacing
sessions later. The harness lives in [`evals/longrun_sim/`](./evals/longrun_sim) and one
command reproduces the run.

| At session 30 | No memory | With AgentMem |
|---|---|---|
| Requirements and lessons still recalled | **0%** | **78%** |
| Recurring failures caught before the repeat | none | **3 of 3** |
| Reminders on routine turns | n/a | 4 of 27 (silence is the default) |
| Memory bank growth | n/a | **1.08x** (bounded by decay + consolidation) |

Every fact behind the probes was still surfaced by the bank at session 30 (9 of 9); the
two graded misses were one-sentence answers tripping the grader, not lost memory. Numbers
from `claude-haiku-4-5` as the memory model, July 2026, about $0.30 of API spend for the
full 30-session run.

The eval also paid for itself: the retention gap it exposed drove three lifecycle fixes
(linking to a lesson now revives it, causally load-bearing entries hold their salience
floor, and the session-start digest ranks by salience). Same model, same scenario:
retention went from 56% to 78%.

Because a layer that interrupts you had better be checkable, every reminder cites a bank
entry id. Auditing 31 real interventions found the citations valid at inject time (31 of 31)
but not durable: consolidation and eviction had retired the entries behind two thirds of
them, so reminders the agent acted on pointed at nothing. Reminders now carry what their
entries said when shown, verified on a fresh run
([audit](./evals/audit/RESULTS.md)).

For how this differs from CLAUDE.md files, Cursor rules, and retrieval APIs like Mem0,
see [docs/comparison.md](./docs/comparison.md); every claim in the AgentMem column links
to code or a measured result in this repo.

The clearest cross-session result comes from the
[LongDebug-Causal harness](./evals/longdebug_causal): multi-session debugging tasks where the
root cause is separated from the symptom by session resets, and the agent is asked at the end
what originally broke. Over nine paired runs on an open model, the no-memory agent cited **zero** files, symbols, or
values that exist anywhere in the repository it had just spent five sessions inside: it wasn't
hedging, it was fluently describing a different project (a React unmount error in a Python
service, a database connection pool where there is no database). **Without memory the agent
doesn't forget, it confabulates.** With the bank attached, all nine answers cite real
artifacts, and on the hardest task it named the buried `constraints.txt` pin that a stronger
model without memory had missed. Grounding is checkable by grep, and
[`score_runs.py`](./evals/longdebug_causal/score_runs.py) regenerates the table.
Details, including the miss, in [RESULTS.md](./evals/longdebug_causal/RESULTS.md). This is the
mirror image of the Terminal-Bench result below: memory earns its keep across sessions, not
inside a single short task.

To watch this on your own code instead of ours: `evals/amnesia/run_amnesia.py
/path/to/your/repo --action-model ...` runs the same probe against any Python repo
with a test suite and writes the two answers side by side, every claim checked
against git.

Those tasks are ours, so the same probe was run on code that isn't: four ordinary chores on
[pallets/click](https://github.com/pallets/click), then on
[python-attrs/attrs](https://github.com/python-attrs/attrs), no gold answer and no planted
trap. Across three runs the no-memory agent invented a file-upload pipeline, a JWT auth
middleware written in TypeScript, and an authentication service, in two pure-Python libraries
that have none of those things, and cited nothing real in any run. With memory, on click it
recalled that the suite had died at collection on pytest 9.1.1 against the pinned 7.4.0, a
real piece of upstream bit-rot it had hit and fixed three sessions earlier, with its context
wiped in between ([RESULTS.md](./evals/realworld/RESULTS.md)). The failure is not an artifact
of tasks we wrote or a repo we picked.

The paper's other benchmark, tau2-bench, ran in full on the airline split: 37 of 50
against 38 of 50, five tickets flipping each way, net one
([RESULTS.md](./evals/tau2/RESULTS.md)). A null, reported as one.

There is also a [Terminal-Bench 2.0 harness](./evals/tbench) that runs real TB tasks on
harbor with the same action loop bare vs memory-attached, hard USD caps on both arms
that count the memory calls too. Three budget-capped runs (23 paired tasks, Haiku and
Sonnet action models, about $14) came out flat on pass rate, and
[`evals/tbench/RESULTS.md`](./evals/tbench/RESULTS.md) says so plainly, with the part
the original paper never reports: what the memory layer costs. The reminders were
accurate throughout; at budget-model prices they just don't repay their turns on
sub-hour tasks. The long-horizon table above is where the layer earns its keep.

## Status

Early and moving fast. The public API (`MemorySession`, `triggers.*`) is the part we keep stable.
Offline tests run without a key (LLM calls are mocked); the long-horizon numbers above come from
the live harness in [`evals/`](./evals).

**Built**

- Core two-phase memory agent, event triggers, JSONL telemetry, and the `agentmem demo`.
- Integrations: Claude Code (daemon-less hooks), the Claude Agent SDK adapter, a LangGraph node,
  Aider, the OpenAI Agents SDK, your own loop (`wrap()`), and an MCP server for pull-style hosts
  like Cursor and Copilot. Each leaves the action agent's prompt, tools, and decoding untouched.
- **Causal memory:** link entries (`caused_by`, `fixed_by`, `rules_out`, and more) so a reminder
  can carry the cause → fix chain across sessions.
- **Continual memory:** salience-based forgetting (active → dormant → archived, nothing
  hard-deleted), a consolidation ladder, and promotion of durable lessons into a project-wide
  bank. See [`docs/how-agentmem-forgets.md`](./docs/how-agentmem-forgets.md).
- **Advantage layer:** a training-free signal that learns, from graded outcomes, when
  intervening tends to pay off, and can gate a would-be reminder back to silence.
- An ablation eval harness with two benchmark suites ([`evals/`](./evals)).

**Next:** live benchmark numbers, a docs site, the first PyPI release, the `agentmem.xyz` landing.

**Later:** a hosted API, and a fine-tuned open-weight memory policy.

## Contributing

Issues and PRs welcome. This only gets good with real trajectories from real agents. Start with
[CONTRIBUTING.md](./CONTRIBUTING.md) and the "good first issue" label. Development is `uv`-based:

```bash
uv sync
uv run pytest          # unit tests; no API key needed (LLM calls are mocked)
uv run ruff check .
uv run mypy packages/agentmem/src
```

## Credits & license

The architecture reimplements, clean-room, the two-phase proactive-memory design from
*"Remember When It Matters: Proactive Memory Agent for Long-Horizon Agents"* (arXiv:2607.08716).
We built from the published paper's specification, not from the authors' code. See
[NOTICE](./NOTICE).

Licensed under [Apache-2.0](./LICENSE).
