# Claude Code

A local daemon plus hooks. The daemon runs memory-steps in the background and hands
cached reminders back to hooks fast, so nothing in Claude Code waits on a model.

## Setup

```bash
pip install agentmem-daemon        # brings in the daemon + FastAPI/uvicorn
cd your-project
agentmem init claude-code          # writes hooks into .claude/settings.json
agentmem serve                     # start the daemon on 127.0.0.1:8642
```

`init` is idempotent and preserves any hooks you already have. Pass `--port` to both
commands to use a different port.

## What the hooks do

The installer wires command hooks that pipe each event to the daemon:

| Hook | Daemon does |
|---|---|
| `SessionStart` | returns a digest of the project's memory from earlier sessions |
| `UserPromptSubmit` | returns any pending reminder; records the prompt |
| `PostToolUse` | records the tool call/result (detecting failures by exit code); returns a pending reminder |
| `PreCompact` | runs a synchronous consolidation step before the transcript is squeezed |
| `SessionEnd` | flushes and persists |

Memory is keyed by working directory, so a project keeps its bank across sessions.

## Notes

- Hooks fall back to a no-op (`|| echo '{}'`) when the daemon isn't running, so they
  can't wedge a session.
- Claude Code's hook payload shape can change between versions. The translation lives
  in one place, `agentmem.integrations.claude_code`, so it's easy to adjust.
