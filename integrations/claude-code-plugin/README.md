# AgentMem plugin for Claude Code

Installs AgentMem's memory hooks into Claude Code as a plugin, so setup is one command
and there's no daemon to run.

## Install

```bash
pip install agentmem-core       # the engine the hooks call
claude plugin install agentmem  # the hooks (this plugin)
export ANTHROPIC_API_KEY=sk-ant-...
```

That's it. Next session, Claude Code fires the plugin's hooks:

- **SessionStart** recaps durable memory from earlier sessions on this project.
- **PostToolUse** watches the run and, when something's worth remembering, computes a
  reminder in the background.
- **UserPromptSubmit** delivers that reminder before the next turn.
- **PreCompact** saves execution state before the transcript is compacted.
- **SessionEnd** consolidates and promotes what proved durable.

Each hook runs `agentmem hook <event>`, which reads the event on stdin and returns fast;
the memory-step's model call happens in a detached process, so nothing blocks the agent.
Run `agentmem doctor` to check the setup.

## What it bundles

| Path | What it is |
|---|---|
| `.claude-plugin/plugin.json` | Plugin manifest. |
| `hooks/hooks.json` | The five command hooks (no daemon). |
| `skills/status/` | `/agentmem:status`, show what's remembered. |

## Prefer a long-running daemon?

The daemon-less hooks fit most setups. If you run at high volume and want the bank kept
warm in memory, use the daemon variant instead of this plugin:

```bash
pip install "agentmem-core[daemon]"
agentmem init claude-code --daemon
agentmem serve
```
