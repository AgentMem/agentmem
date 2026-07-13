# LangGraph

An `AgentMemNode` you place before your action node. It observes new messages from
the state and writes `memory_context` for the action node to read.

```python
from agentmem.integrations.langgraph import make_memory_node

memory = make_memory_node(task="refactor the auth module")
graph.add_node("memory", memory)
graph.add_edge("memory", "agent")   # agent reads state["memory_context"]
```

The node duck-types messages (LangChain objects, `{"role", "content"}` dicts, or
`(role, content)` tuples), so it works without importing LangChain and is easy to test.
`make_memory_node` builds the session for you; pass `session=` to supply your own.
