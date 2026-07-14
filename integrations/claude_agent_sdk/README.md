# Claude Agent SDK

In-process hooks for the [Claude Agent SDK](https://pypi.org/project/claude-agent-sdk/).
No edits to your tools or system prompt, just an added hook.

```bash
pip install "agentmem-core[agent-sdk]"
```

```python
from agentmem.integrations.claude_agent_sdk import attach_memory

options = ClaudeAgentOptions(...)
options = attach_memory(options, task="fix the failing auth tests")
# registers a PostToolUse hook; the live session is on options.agentmem_session
# so you can inspect or close it.
```

AgentMem rides on the SDK's **PostToolUse** hook: it sees each tool call and result,
and returns the pending reminder as `additionalContext`, so the reminder lands on the
tool result right before the agent's next action. The adapter wraps its callback in the
SDK's `HookMatcher` (verified against `claude-agent-sdk` 0.2.x).

The SDK's `UserPromptSubmit` hook is deliberately not used: in the current SDK it
carries no prompt text and can't add context, so it can't observe or inject. PostToolUse
covers the loop.
