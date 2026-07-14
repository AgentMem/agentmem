"""`wrap(action_fn)` folds the two-call integration into one wrapped callable."""

from __future__ import annotations

from pathlib import Path

from agentmem import triggers, wrap
from agentmem._demo import ScriptedProvider
from agentmem.config import AgentMemConfig
from agentmem.schemas import Event


def _fail_events(passed: bool) -> list[Event]:
    return [
        Event(kind="tool_call", tool_name="bash", text="pytest -q"),
        Event(
            kind="tool_result",
            tool_name="bash",
            ok=passed,
            text="ok" if passed else "FAILED test_token_expiry",
        ),
    ]


def test_wrap_injects_the_reminder_and_observes_the_result(tmp_path: Path) -> None:
    seen: list[str | None] = []

    def action(memory_context: str | None) -> list[Event]:
        seen.append(memory_context)
        return _fail_events(passed=False)

    agent = wrap(
        action,
        task="make the tests pass",
        provider=ScriptedProvider(),
        trigger=triggers.default(),
        async_worker=False,
        config=AgentMemConfig(state_dir=str(tmp_path), max_tool_rounds=1),
    )

    agent()  # turn 1: nothing remembered yet
    agent()  # turn 2: the second failure gets diagnosed into a reminder
    agent()  # turn 3: sees the reminder
    agent.close()

    assert seen[0] is None
    assert seen[2] is not None and "DEFAULT_TTL" in seen[2]


def test_wrap_extract_events_pulls_events_from_a_structured_return(tmp_path: Path) -> None:
    class Reply:
        def __init__(self, events: list[Event]) -> None:
            self.new_events = events

    def action(memory_context: str | None) -> Reply:
        return Reply(_fail_events(passed=False))

    with wrap(
        action,
        task="t",
        extract_events=lambda reply: reply.new_events,
        provider=ScriptedProvider(),
        async_worker=False,
        config=AgentMemConfig(state_dir=str(tmp_path), max_tool_rounds=1),
    ) as agent:
        agent()
        agent()
        # The events were observed, so the bank picked up what the scripted run recorded.
        assert not agent.memory.bank.is_empty()
