# Changelog

All notable changes to AgentMem are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once we cut
`0.1.0`.

The public API, `agentmem.MemorySession` and `agentmem.triggers.*`, is the
contract we version against. Breaking it means a note here.

## [Unreleased]

### Added
- Sign a receipt with an Ed25519 key (`agentmem attest keygen | sign | verify`) and its
  integrity verifies offline with only the public key, no trust in AgentMem or the hub. And
  `agentmem ledger export` writes the record as an audit log (JSON or CSV) in the spirit of EU
  AI Act Article 12, which the hub also serves at `/teams/{team}/export`. New in
  `agentmem.verify.attest`; the signing needs the `attest` extra (cryptography).
- `agentmem-hub`, a hosted, multi-tenant team feed (a new package). Contributors run
  `agentmem ledger push --to <hub> --team <t> --key <k>` to send their local receipts; the
  hub chains each into one tamper-evident team timeline (a second hash-chain over the
  sequence it receives, so the server itself cannot silently reorder or drop entries),
  rejects a receipt whose own facts do not hash to its seal, and dedupes by id. It serves the
  team feed as JSON and as a web page that asks for the team key in the browser and carries no
  data or key in its URL. Every team is gated by a bearer key the operator configures via
  `AGENTMEM_HUB_KEYS`. Run it with `agentmem-hub`.
- A shared, multi-actor ledger and a human feed over it. Several actors audit their work on
  one project with `agentmem audit --actor <name>`, and their receipts interleave in one
  hash-chained, append-only record, each attributed and verified; concurrent writes are
  serialized under a file lock so the chain never forks. `agentmem ledger` reads it back as a
  feed (markdown or a self-contained HTML page), filterable by actor or verdict, with
  `--verify` for chain integrity. New in `agentmem.verify`: `Ledger`. The Claude Code
  auto-audit attributes its receipts to `claude-code`.
- `gmail_sent_recorder`, a real cloud/mail recorder on `ApiRecorder`: given an OAuth token it
  lists the user's Gmail Sent folder over the REST API (stdlib only, no Google SDK, transport
  injectable for tests), so "I emailed the customer" is checked against what was actually
  sent. In `agentmem.integrations.gmail`.
- Action audit reaches beyond files. A `Recorder` captures any ground truth an agent acts
  on and diffs it into the same receipt: `GitRecorder` records branches, commits, and tags
  (offline, no token), so a commit shows as evidence, an undisclosed branch is flagged, and
  a claim to have committed that left no trace is caught; `ApiRecorder` does the same for any
  cloud or mail resource you can list, without bundling a vendor SDK. `agentmem audit --git`
  turns it on from the CLI. In the Claude Code plugin it runs itself: a SessionStart hook
  freezes the state and a Stop hook checks the agent's wrap-up against the session's real
  diff. New in `agentmem.verify`: `Recorder`, `Change`, `GitRecorder`, `ApiRecorder`.
- `agentmem audit` verifies what an agent actually *did*, not just what it said. It captures
  the real before and after around a span of work and checks the agent's account against the
  diff, catching fabrication (a file claimed but never touched), overreach (a file changed
  but never mentioned), and silent failure (a check claimed to pass that did not). Receipts
  are hash-chained into an append-only, tamper-evident record, the before-state is stored so
  `audit undo` can put the tree back byte for byte, and `audit end` exits non-zero on a trust
  break so it gates CI. New in `agentmem.verify`: `Snapshot`, `Effect`, `ActionReceipt`,
  `ReceiptStore`, `verify_run`, `undo`. Detection is scored in `evals/action_audit/`
  (12 / 12 scenarios, no false alarms).
- One-click Claude Code install from the plugin marketplace: `/plugin marketplace add
  AgentMem/agentmem` then `/plugin install agentmem@agentmem`, no terminal. The plugin
  bundles a `bin/agentmem-engine` bootstrap that runs the engine off an installed
  `agentmem`, else `uvx`, else `pipx`, and exits clean if none is present, so a missing
  setup can never break a session. Adds an `/agentmem:setup` wizard for first-run and the
  API key. `.claude-plugin/marketplace.json` makes the repo an installable marketplace.

### Changed
- The core package publishes to PyPI as `agentmem-core`: the name `agentmem` was
  already registered by an unrelated project. Nothing else moves, `import agentmem`,
  the `agentmem` CLI, and `agentmem-mcp` are all unchanged, `pip install agentmem-core`
  is the only new spelling. `agentmem-daemon` bumps to 0.1.1 to correct its dependency,
  its published 0.1.0 pointed at the wrong `agentmem` on PyPI.

## [0.1.0] - 2026-07-14

First release on PyPI. Measured on the 30-session LongRun-sim harness: retention 0%
without memory against 78% with it, all three recurring failures caught before the
repeat, bank growth held to 1.08x. See `evals/longrun_sim/`.

### Added
- Monorepo scaffold, `uv` workspace, and CI (ruff + mypy + pytest).
- Core memory bank: `MemoryEntry` / `MemoryBank` schemas and the pure
  `apply_tool_calls` reducer with budget enforcement and eviction (M0).
- JSON-file and SQLite stores behind a single `Store` protocol (M0).
- Two-phase memory agent, bank management (Phase 1) and intervention
  selection (Phase 2), with the Anthropic provider (M1).
- `Injector` with per-entry cooldown, `MemorySession` with a background
  memory-step worker, event triggers, JSONL telemetry, and a secret redactor.
- `agentmem` CLI (`demo`, `replay`, `bank`) and the `toy_loop` example.
- Claude Code integration: the `agentmem-daemon` FastAPI daemon (hook endpoints
  for session-start, prompt, tool use, pre-compact consolidation, and session-end),
  `agentmem serve`, and the `agentmem init claude-code` hook installer. Memory
  persists per project across sessions.
- Claude Agent SDK adapter (`attach_memory`) and a LangGraph node (`AgentMemNode`),
  both leaving the action agent's tools and prompt untouched.
- Eval harness (`agentmem-evals`): the five ablation conditions, a LongDebug-mini
  task format with two seed tasks, a runner (real temp repo + subprocess pytest),
  metrics, a `--max-usd` cap, and `REPORT.md` generation. Offline (scripted) mode
  runs with no key; `--live` drives a real model.
- Causal memory: `MemoryEdge` and a `memory_link` tool (5th tool), so Phase 1 can
  link entries (`caused_by`, `fixed_by`, `rules_out`, `blocks`, `verifies`,
  `supersedes`). Reminders carry the cause/fix chain, Phase 2 gains a counterfactual
  intervention condition, and `agentmem bank --graph` shows the edges. Off by default
  behavior is unchanged (`causal_enabled`).
- Advantage layer (`agentmem.policy`, opt-in via `advantage_enabled`): a training-free,
  JitRL-style learned decision aid. An Outcome Evaluator grades each memory-step at
  SessionEnd; those returns feed a k-NN advantage estimate over state signatures, which
  gives Phase 2 a "in similar past states, injecting averaged +X" prior and a one-way
  gate that can turn a would-be reminder into silence (never the reverse). Fails safe to
  plain behavior with too little history.
- LongDebug-causal benchmark (`evals/longdebug_causal/`): five multi-session debugging
  tasks where the real root cause hides behind a plausible wrong lead: stale build
  artifacts, config drift, a ruled-out lock theory, cross-module blast radius, and a
  superseded version pin. Each task ships a `trap` and a `gold` session script, a hidden
  verifier, and a YAML gold spec (root cause, required keywords, causal edges). `smoke.py`
  proves every trap fires deterministically with zero model tokens before any live run,
  and `judge_prompts.py` holds the judge prompts plus the pure recurrence and
  stale-reminder metrics.
- Continual memory (on by default via `continual_enabled`): a salience score
  (recency + frequency + tag importance + reinforcement) drives an
  active/dormant/archived lifecycle. Nothing is deleted for being unpopular: capacity
  pressure demotes the lowest-salience entry, `policy`/`task` requirements are floored
  into `active`, and archived entries move to cold storage. A consolidation ladder
  (near-duplicate merge, repeated-attempt fusion into an abstract rule) runs at
  PreCompact and SessionEnd. Durable, well-reinforced entries are promoted into a
  separate project bank (rewritten as general rules), which Phase 1/2 render first,
  each tier capped by salience. When the advantage layer is on, the evaluator's
  per-step grades also reinforce the entries each reminder cited. `agentmem bank` shows
  each entry's state and salience; `agentmem bank --tier project` inspects the project
  bank. See `docs/how-agentmem-forgets.md`.
- LongRun-sim benchmark (`evals/longrun_sim/`): 30 interleaved sessions across three
  repos, scoring retention, cross-repo interference, learning-curve slope, and bank
  growth. `metrics.py` and `scenario.py` self-check offline (`--selftest`); the live run
  is gated behind a key.
- Setup diagnostics so a misconfiguration is visible instead of silent: failed
  memory-steps and skipped consolidation/promotion/grading are now logged, not
  swallowed; a session checks its model and key up front (a sync session raises, the
  daemon warns and keeps serving); `agentmem serve` warns at startup on a missing key;
  and a new `agentmem doctor` prints a checklist (model/key, hooks, daemon). The
  litellm provider now advertises itself honestly as planned, not shipped.
- Daemon-less Claude Code integration, now the default: `agentmem init claude-code`
  writes `command` hooks that call `agentmem hook <event>`, so there's no daemon to
  keep running. State lives on disk between the short-lived hook processes (a per-session
  live file plus the pending reminder), and the memory-step's model call is spawned
  detached (`python -m agentmem _step`) so a hook returns in milliseconds. Ships as a
  Claude Code plugin (`integrations/claude-code-plugin/`) for one-command install, with
  a `/agentmem:status` skill. The long-running daemon is still available as opt-in warm
  mode via `agentmem init claude-code --daemon` and `pip install "agentmem-core[daemon]"`.
- `agentmem.wrap(action_fn)`: the one-liner for a hand-written loop. It injects the
  pending reminder as a `memory_context` keyword and observes what the turn returns.
- A committable `agentmem.toml` at the project root pins model/store/trigger settings
  for the whole team (env vars and code still override); see `agentmem.toml.example`.
- Integration correctness: the Claude Agent SDK adapter now wraps its callback in the
  SDK's `HookMatcher` and rides on PostToolUse (the SDK's UserPromptSubmit can't inject),
  with a clear "pip install 'agentmem-core[agent-sdk]'" error when the SDK is missing. The
  LangGraph node documents (and makes configurable) the `memory_context` state key a
  graph must declare.
- Three more integrations, each on the same public API and leaving the action agent
  untouched:
  - An MCP server (`agentmem-core[mcp]`, the `agentmem-mcp` command) exposing `recap`,
    `search`, `bank`, and `checkpoint` as tools, so any MCP host (Cursor, Copilot, Codex,
    Gemini CLI, Continue, Windsurf) can reach project memory. Standard MCP can't push a
    reminder mid-turn, so `checkpoint` is the portable substitute: the server's own
    instructions tell the agent to call it before an edit or after a failure, and it
    returns a silence-gated, id-cited Phase-2-style decision computed on demand against
    the project's salient memory. True mid-turn injection stays with the hook-based hosts.
  - An Aider adapter (`agentmem-core[aider]`): a thin `Coder` subclass injects a transient
    reminder through `format_chat_chunks` (never persisted to Aider's history), while
    `AiderMemory.run()` drives the turn and observes the reply, edited files, and
    test/lint outcome.
  - An OpenAI Agents SDK adapter (`agentmem-core[openai-agents]`): observe through `RunHooks`,
    inject through `RunConfig.call_model_input_filter` right before each model call, so
    the reminder is consumed once and the base instructions are left alone.
- The litellm provider is now implemented (`agentmem-core[litellm]`), so the memory agent can
  run on any backend litellm supports (Gemini, OpenAI, vLLM, Ollama) by setting
  `model="litellm/<backend>"`. It translates our Anthropic-native content blocks, including
  the Phase 1 tool loop, to and from OpenAI's format at the edge.

[Unreleased]: https://github.com/agentmem/agentmem/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/agentmem/agentmem/releases/tag/v0.1.0
