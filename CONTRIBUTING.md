# Contributing to AgentMem

Thanks for taking a look. AgentMem gets good only when it sees real agent
trajectories, so bug reports, traces, and PRs are all genuinely useful. You don't
need to write code to help.

## Ways to help

- **Report a miscalibration.** The hardest problem here is *when* to remind. If AgentMem
  nagged when it should have stayed quiet (or stayed quiet when a reminder would've
  saved a run), open an issue with the `agentmem replay` output. That's gold.
- **Add an integration.** Wrappers for other harnesses (Aider, OpenAI Agents SDK, your
  own loop) are welcome as long as they respect the "action agent unchanged" rule.
- **Improve the eval suite.** More `LongDebug-mini` tasks, more Terminal-Bench coverage.
- **Docs.** If the quickstart didn't just work, that's a bug. Tell us where it broke.

## Development setup

We use [`uv`](https://docs.astral.sh/uv/). Everything runs from the repo root.

```bash
git clone https://github.com/agentmem/agentmem
cd agentmem
uv sync                 # creates .venv and installs the workspace editable
uv run agentmem demo    # sanity check (needs ANTHROPIC_API_KEY)
```

Unit tests need no key and no network, LLM calls are replayed from cassettes:

```bash
uv run pytest
```

## Before you open a PR

Run the same checks CI runs. Green here means green there:

```bash
uv run ruff check --fix .        # lint + import order + autofix
uv run ruff format .             # format
uv run mypy packages/agentmem/src
uv run pytest
```

A PR is ready when:

- New behavior has a test. For the load-bearing pure logic, `bank.apply_tool_calls`,
  triggers, the injector cooldown, the Phase 2 parser, write the test first.
- You didn't loosen a golden test to make it pass. If a golden output changed, explain
  *why* it changed in the PR description.
- The public API (`MemorySession`, `triggers.*`) is untouched, or the break is
  documented in `CHANGELOG.md`.
- No secrets, no absolute local paths, no committed `.agentmem/` state.

## The one hard rule: clean-room

AgentMem reimplements a published architecture from the paper's specification. Do **not**
copy or paste code from the paper authors' reference repository
(`github.com/yifannnwu/proactive-memory-agent`). Reading the paper is encouraged; lifting
their source is not. If you're unsure whether something crosses the line, ask in the PR.

## Design north star

When a change touches the memory agent, weigh it against the paper's ablation findings.
The short version:

1. Don't dump the whole bank at the action agent.
2. Keep the "stay silent" path, and measure how often it's the right call.
3. Every reminder must cite a real entry id.
4. Semantic retrieval is not a substitute for the *when* decision.

If a PR erodes one of those, it needs a very good reason.

## License

By contributing, you agree your work is licensed under [Apache-2.0](./LICENSE), the same
as the rest of the project.
