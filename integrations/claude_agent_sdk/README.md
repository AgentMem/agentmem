# Claude Agent SDK

In-process hooks for the [Claude Agent SDK](https://pypi.org/project/claude-agent-sdk/).
No edits to your tools or system prompt, just added hooks.

```python
from agentmem.integrations.claude_agent_sdk import attach_memory

options = ClaudeAgentOptions(...)
options = attach_memory(options, task="fix the failing auth tests")
# registers UserPromptSubmit + PostToolUse hooks; the live session is on
# options.agentmem_session so you can inspect or close it.
```

The hook callbacks (`MemoryHooks`) do the work: observe tool use, hand back a pending
reminder as `additionalContext`. The SDK's hook-registration shape has shifted between
versions, so `attach_memory` keeps that wiring thin, if your version differs, the
callbacks are the part that matters and they're unchanged.
