<!-- Keep it short. Link the issue this closes if there is one. -->

## What & why

<!-- One or two sentences. What changed, and what problem it solves. -->

Closes #

## Checklist

- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass
- [ ] `uv run mypy packages/agentmem/src` passes
- [ ] `uv run pytest` passes; new behavior has a test
- [ ] Golden tests weren't loosened to go green (or the change is explained above)
- [ ] Public API (`MemorySession`, `triggers.*`) unchanged, or the break is noted in
      `CHANGELOG.md`
- [ ] No secrets, absolute local paths, or committed `.agentmem/` state
- [ ] Clean-room respected — no code lifted from the paper's reference repo
