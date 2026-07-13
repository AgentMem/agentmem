"""Tests for the LangGraph node.

Driven with a recording stand-in for the session, so this checks the node's own job:
converting messages to events, only observing new ones, and returning the context.
"""

from __future__ import annotations

from pathlib import Path

from agentmem._demo import ScriptedProvider
from agentmem.config import AgentMemConfig
from agentmem.integrations.langgraph import AgentMemNode, make_memory_node


class RecordingSession:
    def __init__(self, pending: str | None = None) -> None:
        self.observed: list[list] = []
        self._pending = pending

    def observe(self, events: list) -> None:
        self.observed.append(events)

    def pending_context(self) -> str | None:
        value, self._pending = self._pending, None
        return value


def test_observes_messages_and_returns_context() -> None:
    session = RecordingSession(pending="[AgentMem] remember X")
    node = AgentMemNode(session)

    out = node(
        {"messages": [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "ok"}]}
    )

    assert out == {"memory_context": "[AgentMem] remember X"}
    assert len(session.observed) == 1
    assert [e.role for e in session.observed[0]] == ["user", "assistant"]


def test_only_new_messages_observed_on_second_call() -> None:
    session = RecordingSession()
    node = AgentMemNode(session)

    node({"messages": [{"role": "user", "content": "a"}]})
    node({"messages": [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]})

    assert len(session.observed) == 2
    assert len(session.observed[1]) == 1  # only the new one
    assert session.observed[1][0].text == "b"


def test_handles_langchain_object_tuple_and_dict() -> None:
    class LCMessage:
        type = "human"
        content = "from object"

    session = RecordingSession()
    node = AgentMemNode(session)
    node(
        {"messages": [("user", "from tuple"), LCMessage(), {"role": "ai", "content": "from dict"}]}
    )

    events = session.observed[0]
    assert (events[0].role, events[0].text) == ("user", "from tuple")
    assert (events[1].role, events[1].text) == ("user", "from object")  # human -> user
    assert events[2].role == "assistant"  # ai -> assistant


def test_no_messages_means_no_observe() -> None:
    session = RecordingSession()
    node = AgentMemNode(session)
    assert node({}) == {"memory_context": None}
    assert session.observed == []


def test_make_memory_node_builds_a_working_node(tmp_path: Path) -> None:
    node = make_memory_node(
        "fix the tests",
        provider=ScriptedProvider(),
        config=AgentMemConfig(state_dir=str(tmp_path), max_tool_rounds=1),
        session_id="lg",
        async_worker=False,
    )
    out = node({"messages": [{"role": "user", "content": "start"}]})
    assert "memory_context" in out  # runs end to end without a real graph
