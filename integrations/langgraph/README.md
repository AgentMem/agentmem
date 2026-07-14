# LangGraph

An `AgentMemNode` you place before your action node. It observes new messages from
the state and writes the pending reminder into `memory_context` for the action node
to read.

```python
from typing import Annotated, TypedDict

from langgraph.graph import add_messages
from agentmem.integrations.langgraph import make_memory_node


class State(TypedDict):
    messages: Annotated[list, add_messages]
    memory_context: str | None          # AgentMemNode writes this; declare it

memory = make_memory_node(task="refactor the auth module")
graph.add_node("memory", memory)
graph.add_edge("memory", "agent")       # agent reads state["memory_context"]
```

**Declare `memory_context` in your state schema.** A strict `TypedDict` / `StateGraph`
schema silently drops (or rejects) an undeclared key, so the reminder would never reach
your action node. Both key names are configurable: `make_memory_node(..., messages_key=,
context_key=)`.

The node duck-types messages (LangChain objects, `{"role", "content"}` dicts, or
`(role, content)` tuples), so it works without importing LangChain and is easy to test.
`make_memory_node` builds the session for you; pass `session=` to supply your own.
