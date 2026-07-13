# Changelog

All notable changes to AgentMem are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims
to follow [Semantic Versioning](https://semver.org/spec/v2.0.0.html) once we cut
`0.1.0`.

The public API, `agentmem.MemorySession` and `agentmem.triggers.*`, is the
contract we version against. Breaking it means a note here.

## [Unreleased]

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

[Unreleased]: https://github.com/agentmem/agentmem/commits/main
