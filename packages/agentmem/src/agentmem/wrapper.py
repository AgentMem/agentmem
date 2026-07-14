"""`wrap(action_fn)`: the one-liner for a hand-written loop."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .config import AgentMemConfig
from .llm.base import LLMProvider
from .session import MemorySession
from .triggers import Trigger


class WrappedAgent:
    """Your turn function with memory riding along. Call it like the original; it reads
    the pending reminder, passes it as `memory_context=`, and observes the result.

    `extract_events` turns the return value into trajectory events. Omit it if your
    function already returns events (or dicts/strings observe() understands); pass e.g.
    `extract_events=lambda reply: reply.new_messages` for a structured return."""

    def __init__(
        self,
        action_fn: Callable[..., Any],
        *,
        task: str,
        extract_events: Callable[[Any], Any] | None = None,
        **session_kwargs: Any,
    ) -> None:
        self._fn = action_fn
        self._extract = extract_events
        self.memory = MemorySession(task=task, **session_kwargs)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        reminder = self.memory.pending_context()
        result = self._fn(*args, memory_context=reminder, **kwargs)
        events = self._extract(result) if self._extract is not None else result
        if events is not None:
            self.memory.observe(events)
        return result

    def close(self) -> None:
        self.memory.close()

    def __enter__(self) -> WrappedAgent:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def wrap(
    action_fn: Callable[..., Any],
    *,
    task: str,
    extract_events: Callable[[Any], Any] | None = None,
    model: str | None = None,
    trigger: Trigger | None = None,
    config: AgentMemConfig | None = None,
    provider: LLMProvider | None = None,
    async_worker: bool = True,
) -> WrappedAgent:
    """Wrap `action_fn` so AgentMem reads a reminder before each call and observes the
    result after. Your function must accept a `memory_context` keyword. Returns a
    callable; close it (or use it as a context manager) to flush and persist."""
    return WrappedAgent(
        action_fn,
        task=task,
        extract_events=extract_events,
        model=model,
        trigger=trigger,
        config=config,
        provider=provider,
        async_worker=async_worker,
    )


__all__ = ["WrappedAgent", "wrap"]
