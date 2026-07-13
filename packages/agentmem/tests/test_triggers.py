"""Tests for the trigger predicates."""

from __future__ import annotations

from agentmem import triggers
from agentmem.schemas import Event
from agentmem.triggers import TriggerState


def _state(turn: int, batch: list[Event], history: list[Event], since: int) -> TriggerState:
    return TriggerState(turn=turn, batch=batch, history=history, turns_since_step=since)


def test_every_n_fires_on_first_turn() -> None:
    trig = triggers.every_n(3)
    assert trig(_state(1, [], [], since=0)) == "first_step"


def test_every_n_fires_on_interval() -> None:
    trig = triggers.every_n(3)
    assert trig(_state(4, [], [], since=3)) == "interval"
    assert trig(_state(3, [], [], since=2)) is None


def test_tool_failure_fires_only_on_failed_result() -> None:
    trig = triggers.on_tool_failure()
    ok = Event(kind="tool_result", tool_name="bash", ok=True, text="passed")
    bad = Event(kind="tool_result", tool_name="bash", ok=False, text="exit 1")
    assert trig(_state(2, [ok], [ok], since=1)) is None
    assert trig(_state(2, [bad], [bad], since=1)) == "tool_failure"


def test_repeat_command_detects_near_identical() -> None:
    trig = triggers.on_repeat_command(window=6)
    c1 = Event(kind="tool_call", tool_name="bash", text="pytest -q")
    c2 = Event(kind="tool_call", tool_name="bash", text="  PYTEST   -q ")  # same, normalized
    history = [c1, c2]
    assert trig(_state(2, [c2], history, since=1)) == "repeat_command"


def test_repeat_command_ignores_distinct() -> None:
    trig = triggers.on_repeat_command(window=6)
    c1 = Event(kind="tool_call", tool_name="bash", text="ls")
    c2 = Event(kind="tool_call", tool_name="bash", text="pytest")
    assert trig(_state(2, [c2], [c1, c2], since=1)) is None


def test_any_of_collects_reasons() -> None:
    bad = Event(kind="tool_result", ok=False, text="boom")
    trig = triggers.any_of(triggers.every_n(3), triggers.on_tool_failure())
    # First turn AND a failure -> both fire, both named (so cooldown-bypass still sees it).
    reason = trig(_state(1, [bad], [bad], since=0))
    assert reason is not None
    assert "first_step" in reason and "tool_failure" in reason


def test_all_of_requires_every_child() -> None:
    bad = Event(kind="tool_result", ok=False, text="boom")
    trig = triggers.all_of(triggers.every_n(1), triggers.on_tool_failure())
    assert trig(_state(2, [bad], [bad], since=1)) is not None
    ok = Event(kind="tool_result", ok=True, text="fine")
    assert trig(_state(2, [ok], [ok], since=1)) is None


def test_default_is_interval_or_failure() -> None:
    trig = triggers.default(every=3)
    bad = Event(kind="tool_result", ok=False, text="boom")
    assert trig(_state(2, [bad], [bad], since=1)) == "tool_failure"
    assert trig(_state(1, [], [], since=0)) == "first_step"
