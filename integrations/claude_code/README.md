# Claude Code

Two ways to wire AgentMem into Claude Code. Both use hooks; neither touches the action
agent's prompt or tools.

## Daemon-less (default)

Command hooks that call `agentmem hook <event>` directly. No process to keep running.

```bash
pip install agentmem-core
cd your-project
agentmem init claude-code           # writes daemon-less hooks into .claude/settings.json
export ANTHROPIC_API_KEY=sk-ant-...
agentmem doctor                     # verify key, model, hooks
```

Or install the whole thing as a plugin (see
[`../claude-code-plugin/`](../claude-code-plugin)):

```bash
pip install agentmem-core
claude plugin install agentmem
```

Each hook is a short-lived process, so state lives on disk between calls: the bank in
`.agentmem/`, a small live-state file, and the pending reminder. The memory-step's model
call is spawned detached, so the hook itself returns in milliseconds.

## Warm mode (optional daemon)

For high-volume use, a long-running daemon keeps the bank in memory:

```bash
pip install "agentmem-core[daemon]"
agentmem init claude-code --daemon
agentmem serve                      # 127.0.0.1:8642
```

The `--daemon` hooks pipe each event to the daemon over curl and fall back to a no-op
(`|| echo '{}'`) when it isn't running, so they can't wedge a session.

## What the hooks do

| Hook | Behavior |
|---|---|
| `SessionStart` | recap the project's memory from earlier sessions |
| `UserPromptSubmit` | deliver any pending reminder before the turn |
| `PostToolUse` | record the tool call/result (failures detected by exit code); trigger a step |
| `PreCompact` | run a step before the transcript is squeezed |
| `SessionEnd` | consolidate, promote, persist |

Memory is keyed by working directory, so a project keeps its bank across sessions.
Claude Code's hook payload shape can change between versions; the translation lives in
one place, `agentmem.integrations.claude_code`, so it's easy to adjust.
