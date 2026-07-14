# integrations/

Adapters that wire AgentMem into a specific agent harness. They all depend on the
`agentmem` core; the core depends on none of them. The rule every integration
follows: **don't change the action agent**, no edits to its system prompt, tools, or
decoding. Reminders go in as transient context and nothing else.

The importable adapters live inside the package as `agentmem.integrations.*`; this
directory holds the docs and runnable examples for each.

| Adapter | Setup | Docs |
|---|---|---|
| Claude Code | `claude plugin install agentmem`, or `agentmem init claude-code` (daemon-less) | [`claude_code/`](./claude_code) · [plugin](./claude-code-plugin) |
| Claude Agent SDK | `from agentmem.integrations.claude_agent_sdk import attach_memory` | [`claude_agent_sdk/`](./claude_agent_sdk) |
| LangGraph | `from agentmem.integrations.langgraph import AgentMemNode` | [`langgraph/`](./langgraph) |
| Your own loop | just `MemorySession`, no adapter needed | [`examples/toy_loop.py`](./examples/toy_loop.py) |
