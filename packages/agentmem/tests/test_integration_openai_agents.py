"""The OpenAI Agents SDK adapter. The SDK isn't installed, so the observe/inject logic
is tested through its pure helpers plus a real session."""

from __future__ import annotations

from pathlib import Path

import pytest
from agentmem._demo import ScriptedProvider
from agentmem.config import AgentMemConfig
from agentmem.integrations import openai_agents as oa
from agentmem.session import MemorySession
from agentmem.triggers import default


def test_message_events_keeps_user_and_assistant_text_and_advances() -> None:
    items = [
        {"role": "user", "content": "add a flag"},
        {"role": "assistant", "content": "done"},
        {"role": "user", "content": ""},  # empty, skipped
        {"role": "tool", "content": "output"},  # not a turn, skipped
    ]
    events = oa._message_events(items, 0)
    assert [(e.role, e.text) for e in events] == [("user", "add a flag"), ("assistant", "done")]
    assert oa._message_events(items, 2) == []  # nothing citable past the high-water mark


def test_tool_event_flags_failure_from_the_text() -> None:
    assert oa._tool_event("pytest", "FAILED test_token_expiry").ok is False
    assert oa._tool_event("bash", "Traceback (most recent call last)").ok is False
    assert oa._tool_event("ls", "app.py\nconfig.py").ok is True


def test_apply_reminder_appends_a_transient_developer_message() -> None:
    base = [{"role": "user", "content": "q"}]
    out = oa.apply_reminder(base, "fix DEFAULT_TTL (K-001)")
    assert out[-1] == {"role": "developer", "content": "fix DEFAULT_TTL (K-001)"}
    assert oa.apply_reminder(base, None) == base  # nothing to inject


def test_attach_memory_points_at_the_extra_without_the_sdk() -> None:
    with pytest.raises(ImportError, match=r"agentmem-core\[openai-agents\]"):
        oa.attach_memory(task="t")


def test_observe_and_stage_stages_a_reminder_after_repeated_failure(tmp_path: Path) -> None:
    session = MemorySession(
        task="make the tests pass",
        provider=ScriptedProvider(),
        trigger=default(),
        async_worker=False,
        config=AgentMemConfig(state_dir=str(tmp_path), max_tool_rounds=1),
    )
    ctx = oa.MemoryContext(session=session)
    for _ in range(3):
        oa._observe_and_stage(ctx, [oa._tool_event("pytest", "FAILED test_token_expiry")])
    session.close()

    assert ctx.pending_reminder is not None and "DEFAULT_TTL" in ctx.pending_reminder
