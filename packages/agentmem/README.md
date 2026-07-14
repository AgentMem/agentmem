# agentmem-core

The core of [AgentMem](https://github.com/agentmem/agentmem): a proactive memory layer
for long-horizon coding agents. It maintains a structured memory bank and decides *when*
to remind your agent, instead of dumping everything or retrieving on similarity.

```bash
pip install agentmem-core
```

Published as `agentmem-core` (the name `agentmem` was already taken on PyPI by an
unrelated project); everything you import and run is still `agentmem`.

```python
from agentmem import MemorySession, triggers

mem = MemorySession(task="Fix the auth tests without changing the public API")
while not done:
    reminder = mem.pending_context()          # str | None
    reply = call_your_agent(messages, memory_context=reminder)
    mem.observe(reply.new_messages)
```

Full docs, integrations, and the design rationale live in the
[main repository](https://github.com/agentmem/agentmem).

Licensed under Apache-2.0.
