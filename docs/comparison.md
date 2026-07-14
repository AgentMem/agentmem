# How AgentMem differs from memory files, rules, and retrieval APIs

Snapshot as of July 2026; the other tools ship fast, so check their docs for
anything load-bearing. The short version: those are all good ways to *store or
retrieve* context. AgentMem's job starts after storage: a second agent watches the
trajectory and decides, turn by turn, whether the next action deserves a reminder,
with silence as the default. Every AgentMem cell links to the code or the measured
result backing it.

| | AgentMem | Claude Code memory (CLAUDE.md, auto memory) | Cursor rules and memories | Mem0 |
|---|---|---|---|---|
| When memory reaches the agent | Pushed mid-task, into the very next turn, when a trigger and a two-phase decision say it matters ([injector.py](../packages/agentmem/src/agentmem/injector.py), [session.py](../packages/agentmem/src/agentmem/session.py)) | Loaded at session start as instructions | Attached to context per rules the user or IDE configures | Returned when the app calls `search()`; the developer decides where it goes |
| Decides when to stay silent | Yes, silence is the default action and it is measured: 4 reminders across 27 routine turns in the 30-session run ([prompts.py](../packages/agentmem/src/agentmem/agent/prompts.py), [README, Measured](../README.md#measured)) | Not applicable, always in context | Not applicable, rules apply passively | Not applicable, retrieval answers every query it is asked |
| Reminder contract | At most 4 bullets and 120 tokens, every bullet cites a bank entry id, consumed once and never persisted into prompts ([injector.py](../packages/agentmem/src/agentmem/injector.py)) | Free-form file text | Free-form rule text | Raw retrieved memories; formatting is the app's job |
| Memory lifecycle | Salience score with decay half-life, active, dormant and archived tiers, revive-on-link, floors for policy and task entries ([salience.py](../packages/agentmem/src/agentmem/salience.py)) | Manual editing | Manual curation of rules and generated memories | Extraction plus entity linking; lifecycle not a headline feature |
| Structure between memories | Six typed causal edges (caused_by, fixed_by, rules_out, verifies, blocks, supersedes) with a counterfactual check before linking ([schemas.py](../packages/agentmem/src/agentmem/schemas.py), [bank.py](../packages/agentmem/src/agentmem/bank.py)) | None | None | Entities extracted and linked across memories (their wording) |
| Learns from outcomes | Every inject-or-silent decision is recorded and graded after the session; a one-way gate can learn to hold back, never to spam ([policy/](../packages/agentmem/src/agentmem/policy/)) | No | No | Not a published feature |
| Long-horizon evidence | 30 interleaved sessions, 3 repos: recall of stated requirements and past lessons went 0% without memory to 78% with it, recurring failures caught 3 of 3 ([evals/longrun_sim/](../evals/longrun_sim/), [README, Measured](../README.md#measured)) | Not published | Not published | Publishes strong retrieval benchmarks (LoCoMo and others); different axis: recall quality, not intervention timing |
| Publishes what memory costs | Yes, including the runs where it did not pay for itself: hard USD caps that count memory calls, cost and turn overhead per trial ([evals/tbench/RESULTS.md](../evals/tbench/RESULTS.md)) | No | No | Publishes latency and retrieval token budgets, not intervention cost against a paired baseline |
| Where it plugs in | Claude Code hooks and plugin, Claude Agent SDK, Aider, OpenAI Agents SDK, LangGraph node, your own loop via `wrap()`, plus an MCP server for Cursor, Copilot, Codex and Gemini CLI ([integrations](../packages/agentmem/src/agentmem/integrations/), [wrapper.py](../packages/agentmem/src/agentmem/wrapper.py), [mcp.py](../packages/agentmem/src/agentmem/mcp.py)) | Claude Code | Cursor | Broad API plus agent skills, including coding agents |
| Runs and tests offline | 314 tests, no network and no key needed; LLM calls mocked with cassettes ([tests](../packages/agentmem/tests/)) | n/a | n/a | Depends on setup |

Two honest notes. First, these tools compose rather than compete: AgentMem's MCP
server sits happily next to CLAUDE.md files, and nothing stops an app from using
Mem0 for user-profile recall while AgentMem watches the execution loop. Second,
the row that matters most is the one nobody else fills in: a paired baseline with
the memory layer's own cost on the bill. That table exists here even where it is
flat, because a dev who catches you hiding one number stops believing the rest.
