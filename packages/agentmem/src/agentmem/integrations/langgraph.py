"""A LangGraph node that plugs AgentMem into a graph.

Drop `AgentMemNode` into your graph before the action node: it observes new messages
from the state and writes `memory_context` for the action node to read. It duck-types
the messages (LangChain objects, dicts, or (role, content) tuples), so importing
LangChain isn't required to use or test it.
"""

from __future__ import annotations

from typing import Any

from ..schemas import Event


class AgentMemNode:
    """Reads new messages off the state, returns a `memory_context` update.

    Nodes see the whole accumulated message list each call, so we track how many
    we've already observed and only feed the new ones.
    """

    def __init__(self, session: Any, messages_key: str = "messages") -> None:
        self._session = session
        self._key = messages_key
        self._seen = 0

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        messages = state.get(self._key, []) or []
        new = messages[self._seen :]
        self._seen = len(messages)

        events = [_to_event(m) for m in new]
        if events:
            self._session.observe(events)

        return {"memory_context": self._session.pending_context()}


def make_memory_node(task: str, *, session: Any = None, **session_kwargs: Any) -> AgentMemNode:
    """Convenience: build a MemorySession and wrap it in a node in one call."""
    if session is None:
        from ..session import MemorySession

        session = MemorySession(task=task, **session_kwargs)
    return AgentMemNode(session)


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
