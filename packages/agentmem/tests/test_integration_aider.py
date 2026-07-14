"""The Aider adapter: transient reminder in, trajectory out. No aider install needed,
the coder-facing parts are exercised with a fake coder."""

from __future__ import annotations

from pathlib import Path

import pytest
from agentmem._demo import ScriptedProvider
from agentmem.config import AgentMemConfig
from agentmem.integrations import aider
from agentmem.session import MemorySession
from agentmem.triggers import default


class _FakeChunks:
    def __init__(self) -> None:
        self.reminder: list[dict[str, str]] = [{"role": "system", "content": "aider's own"}]


class _FakeCoder:
    """Stands in for a real MemoryCoder: records the reminder it saw, reports a failing
    turn."""

    def __init__(self) -> None:
        self.agentmem_reminder: str | None = None
        self.seen: list[str | None] = []
        self.aider_edited_files: set[str] = set()
        self.test_outcome: bool | None = None
        self.lint_outcome: bool | None = None

    def run(self, with_message: str, **_: object) -> str:
        self.seen.append(self.agentmem_reminder)
        self.aider_edited_files = {"config.py"}
        self.test_outcome = False
        return f"edited for: {with_message}"


def test_append_reminder_is_transient_and_appends() -> None:
    chunks = _FakeChunks()
    aider._append_reminder(chunks, "fix DEFAULT_TTL (K-001)")
    assert chunks.reminder[-1] == {"role": "system", "content": "fix DEFAULT_TTL (K-001)"}
    assert chunks.reminder[0] == {"role": "system", "content": "aider's own"}  # kept aider's


def test_events_from_turn_maps_reply_edits_and_outcomes() -> None:
    class _C:
        aider_edited_files = {"b.py", "a.py"}
        test_outcome = False
        lint_outcome = True

    events = aider._events_from_turn("do it", "done", _C())
    shape = [(e.kind, e.role, e.tool_name, e.ok, e.text) for e in events]
    assert shape == [
        ("message", "user", None, True, "do it"),
        ("message", "assistant", None, True, "done"),
        ("tool_call", "", "edit", True, "a.py"),
        ("tool_call", "", "edit", True, "b.py"),
        ("tool_result", "", "test", False, "test failed"),
        ("tool_result", "", "lint", True, "lint passed"),
    ]


def test_make_memory_coder_points_at_the_extra_without_aider() -> None:
    with pytest.raises(ImportError, match=r"agentmem\[aider\]"):
        aider.make_memory_coder(main_model=object(), io=object())


def test_aider_memory_injects_the_reminder_then_observes(tmp_path: Path) -> None:
    session = MemorySession(
        task="make the tests pass",
        provider=ScriptedProvider(),
        trigger=default(),
        async_worker=False,
        config=AgentMemConfig(state_dir=str(tmp_path), max_tool_rounds=1),
    )
    coder = _FakeCoder()
    with aider.AiderMemory(session, coder) as mem:
        mem.run("try a fix")  # turn 1: nothing remembered yet
        mem.run("try again")  # turn 2: the repeated failure gets diagnosed
        mem.run("once more")  # turn 3: the reminder is injected

    assert coder.seen[0] is None
    assert coder.seen[2] is not None and "DEFAULT_TTL" in coder.seen[2]
