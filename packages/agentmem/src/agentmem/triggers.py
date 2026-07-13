"""When to run a memory-step.

Triggers are composable predicates over the recent trajectory. A trigger returns a
short reason string when it wants a step, or None to stay quiet. The reason flows
into telemetry; for tool failures it also tells the injector it may bypass the
cooldown.

The shipped default is `default()`: run on an interval or on any tool failure.
`paper_faithful()` runs every step, for eval comparisons.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from .schemas import Event

Trigger = Callable[["TriggerState"], "str | None"]


@dataclass
class TriggerState:
    """What triggers see, assembled by the session each turn."""

    turn: int  # 1-based index of the current action-turn
    batch: list[Event] = field(default_factory=list)  # events observed this turn
    history: list[Event] = field(default_factory=list)  # everything so far
    turns_since_step: int = 0  # turns since the last memory-step fired


def every_n(n: int = 3) -> Trigger:
    """First turn, then every n turns after a step."""

    def trigger(state: TriggerState) -> str | None:
        if state.turn == 1:
            return "first_step"
        if state.turns_since_step >= n:
            return "interval"
        return None

    return trigger


def on_tool_failure() -> Trigger:
    """Fire when a tool errored this turn (non-zero exit, failing test)."""

    def trigger(state: TriggerState) -> str | None:
        for event in state.batch:
            if event.kind == "tool_result" and not event.ok:
                return "tool_failure"
        return None

    return trigger


def on_repeat_command(window: int = 6) -> Trigger:
    """Fire when the latest command closely repeats a recent one (a stuck loop)."""

    def trigger(state: TriggerState) -> str | None:
        commands = [_normalize(e.text) for e in state.history if e.kind == "tool_call"]
        if len(commands) < 2:
            return None
        latest = commands[-1]
        if latest and latest in commands[-window - 1 : -1]:
            return "repeat_command"
        return None

    return trigger


def any_of(*triggers: Trigger) -> Trigger:
    """Fire if any child fires; the reason lists all that did.

    We collect every reason instead of short-circuiting so "tool_failure" stays
    visible when the interval trigger also fired (that's what enables the bypass).
    """

    def trigger(state: TriggerState) -> str | None:
        reasons = [r for t in triggers if (r := t(state))]
        return "+".join(reasons) if reasons else None

    return trigger


def all_of(*triggers: Trigger) -> Trigger:
    """Fire only if every child fires."""

    def trigger(state: TriggerState) -> str | None:
        reasons = [t(state) for t in triggers]
        if all(reasons):
            return "+".join(r for r in reasons if r)
        return None

    return trigger


def default(every: int = 3) -> Trigger:
    """Interval or tool failure. The shipped default."""
    return any_of(every_n(every), on_tool_failure())


def paper_faithful() -> Trigger:
    """Every step, no event triggers, for apples-to-apples eval runs."""
    return every_n(1)


def _normalize(command: str) -> str:
    return re.sub(r"\s+", " ", command.strip().lower())
