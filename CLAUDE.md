# AgentMem, project instructions for Claude Code

## What this repo is
A proactive memory layer for coding agents, implementing the two-phase
memory-intervention architecture from arXiv:2607.08716. Start with the README for the
architecture and the public API.

## Golden rules
- **Action-agent-agnostic.** The core never assumes a specific harness. Integrations
  depend on the core; the core depends on none of them.
- **Silence is a first-class action.** Phase 2 returns `<no_intervention/>` most of
  the time. Parse failures default to silence, never to a guess.
- **Reminders stay small and grounded.** Never more than 4 bullets / 120 tokens, and
  every bullet cites an entry id (e.g. `(K-004)`).
- **Reminders are transient.** Consumed once, never persisted into base instructions
  or the action agent's system prompt.
- **Clean-room.** Do not copy code from github.com/yifannnwu/proactive-memory-agent.
  We build from the spec, not their source.

## Commands
- Setup: `uv sync`
- Test (unit, no network): `uv run pytest`
- Test (integration, real API): `uv run pytest -m integration`  # needs ANTHROPIC_API_KEY
- Lint + format: `uv run ruff check --fix . && uv run ruff format .`
- Types: `uv run mypy packages/agentmem/src`
- Demo: `uv run agentmem demo`
- Daemon: `uv run agentmem serve --port 8642`

## Conventions
- Python 3.11+, Pydantic v2, full type hints. Background/daemon paths use threads or
  asyncio; the LLM provider interface is synchronous.
- **Tests first** for the load-bearing pure logic: `bank.apply_tool_calls`, trigger
  predicates, injector cooldown, and the Phase 2 parser.
- LLM calls in tests are mocked with respx cassettes under `tests/cassettes/`. No unit
  test should touch the network or need a key.
- Prompts live only in `agent/prompts.py`. Treat edits there as behavior changes.
- The public API (`agentmem.MemorySession`, `agentmem.triggers.*`) is stable. Breaking
  it means a note in CHANGELOG.md in the same PR.

## Definition of done (every PR)
Lint + mypy + pytest green; new behavior covered by tests; no secrets and no absolute
local paths committed.
