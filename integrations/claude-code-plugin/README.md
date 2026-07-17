# AgentMem plugin for Claude Code

Proactive memory for Claude Code, installed from the plugin marketplace. No daemon to run,
and no manual Python setup: the hooks fetch the engine themselves the first time they fire.

## Install

Inside Claude Code, run two commands:

```
/plugin marketplace add AgentMem/agentmem
/plugin install agentmem@agentmem
```

Then, once, so the memory step can reach the model:

```
/agentmem:setup
```

That last one is a friendly wizard: it checks the engine, helps you set an Anthropic API
key (needed for the memory step, separate from a Claude subscription), and confirms
everything is ready. That's the whole setup, no terminal required.

## What happens next

From the next session on, Claude Code fires the plugin's hooks:

- **SessionStart** recaps durable memory from earlier sessions, and freezes the ground
  truth (files and git) so the session can be audited.
- **PostToolUse** watches the run and, when something's worth remembering, computes a
  reminder in the background.
- **UserPromptSubmit** delivers that reminder before the next turn.
- **PreCompact** saves execution state before the transcript is compacted.
- **Stop** reads the agent's own wrap-up and checks it against the session's real diff. If
  the summary does not match what changed, you are told; a faithful session stays silent.
- **SessionEnd** consolidates and promotes what proved durable.

Each hook runs `bin/agentmem-engine hook <event>`, a small wrapper that finds the engine
(an installed `agentmem`, else `uvx`, else `pipx`) and passes the event through on stdin.
It returns fast; the memory-step's model call happens in a detached process, so nothing
blocks the agent. If no engine and no installer are present, the wrapper exits cleanly and
prints one hint, so a missing setup can never break your session.

For the snappiest hooks, install the engine once so it stays on PATH:

```bash
uv tool install agentmem-core
```

## What it bundles

| Path | What it is |
|---|---|
| `.claude-plugin/plugin.json` | Plugin manifest. |
| `bin/agentmem-engine` | Bootstrap wrapper: runs the engine without a manual pip. |
| `hooks/hooks.json` | The memory hooks plus the auto-audit (no daemon). |
| `skills/setup/` | `/agentmem:setup`, the first-time wizard. |
| `skills/status/` | `/agentmem:status`, show what's remembered. |

## Prefer a long-running daemon?

The daemon-less hooks fit most setups. If you run at high volume and want the bank kept
warm in memory, use the daemon variant instead of this plugin:

```bash
pip install "agentmem-core[daemon]"
agentmem init claude-code --daemon
agentmem serve
```
