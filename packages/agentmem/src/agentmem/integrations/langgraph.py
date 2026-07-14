"""A LangGraph node that plugs AgentMem into a graph.

Drop `AgentMemNode` into your graph before the action node: it observes new messages
from the state and writes the pending reminder into `memory_context` for the action
node to read. It duck-types the messages (LangChain objects, dicts, or (role, content)
tuples), so importing LangChain isn't required to use or test it.

Your graph's state must declare the two keys this node touches: `messages` (read) and
`memory_context` (written). A strict `TypedDict`/`StateGraph` schema will drop or reject
an undeclared key, so add it, for example:

    class State(TypedDict):
        messages: Annotated[list, add_messages]
        memory_context: str | None

Both key names are configurable via `messages_key` / `context_key`.
"""

from __future__ import annotations

from typing import Any

from ..schemas import Event

# The state key AgentMemNode writes the reminder into (the action node reads it).
DEFAULT_CONTEXT_KEY = "memory_context"


class AgentMemNode:
    """Reads new messages off the state, returns a `{context_key: reminder}` update.

    Nodes see the whole accumulated message list each call, so we track how many
    we've already observed and only feed the new ones. `context_key` is the state key
    the update is written under; declare it in your graph's state schema.
    """

    def __init__(
        self,
        session: Any,
        messages_key: str = "messages",
        context_key: str = DEFAULT_CONTEXT_KEY,
    ) -> None:
        self._session = session
        self._key = messages_key
        self._context_key = context_key
        self._seen = 0

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        messages = state.get(self._key, []) or []
        new = messages[self._seen :]
        self._seen = len(messages)

        events = [_to_event(m) for m in new]
        if events:
            self._session.observe(events)

        return {self._context_key: self._session.pending_context()}


def make_memory_node(
    task: str,
    *,
    session: Any = None,
    messages_key: str = "messages",
    context_key: str = DEFAULT_CONTEXT_KEY,
    **session_kwargs: Any,
) -> AgentMemNode:
    """Convenience: build a MemorySession and wrap it in a node in one call."""
    if session is None:
        from ..session import MemorySession

        session = MemorySession(task=task, **session_kwargs)
    return AgentMemNode(session, messages_key=messages_key, context_key=context_key)


def _to_event(message: Any) -> Event:
    role, content = _role_and_content(message)
    if role in ("tool", "function"):
        return Event(kind="tool_result", tool_name="tool", text=content)
    mapped = {"human": "user", "ai": "assistant", "assistant": "assistant", "user": "user"}
    return Event(kind="message", role=mapped.get(role, role or "assistant"), text=content)


def _role_and_content(message: Any) -> tuple[str, str]:
    # LangChain BaseMessage: .type + .content
    role = getattr(message, "type", None)
    content = getattr(message, "content", None)
    if role is not None or content is not None:
        return str(role or ""), _stringify(content)
    # dict form: {"role"/"type", "content"}
    if isinstance(message, dict):
        return str(message.get("role") or message.get("type") or ""), _stringify(
            message.get("content")
        )
    # (role, content) tuple
    if isinstance(message, (tuple, list)) and len(message) == 2:
        return str(message[0]), _stringify(message[1])
    return "", _stringify(message)


def _stringify(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    # LangChain sometimes uses a list of content blocks; join their text.
    if isinstance(content, list):
        parts = [b.get("text", "") if isinstance(b, dict) else str(b) for b in content]
        return " ".join(p for p in parts if p)
    return str(content)
