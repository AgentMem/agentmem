"""The five conditions we compare, as strategy objects.

They all wrap the same action agent; only how (and whether) memory reaches it each
turn varies:

  baseline         no memory at all
  agentmem         the real thing: maintain a bank, intervene selectively
  full_bank        maintain a bank, but dump the whole thing every turn
  always_inject    maintain a bank, always surface its latest entry (no silence)
  injection_only   no bank; a generic nudge after a failure

Offline (scripted agent) cleanly shows memory-vs-baseline. Separating the memory
conditions from each other needs a real model that can get distracted or over-nagged,
so those are wired and ready for live runs but won't spread out offline.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentmem import MemorySession
from agentmem.config import AgentMemConfig
from agentmem.schemas import Event
from agentmem.telemetry import read_events

from .task import Task


class Strategy:
    """Base: no memory. Subclasses override context()/observe()."""

    name = "baseline"

    def __init__(self, task: Task, state_dir: Path, memory_provider: Any = None) -> None:
        self.task = task
        self.state_dir = state_dir
        self.interventions = 0
        self._session: MemorySession | None = None

    def context(self) -> str | None:
        return None

    def observe(self, events: list[Event]) -> None:
        pass

    def close(self) -> None:
        if self._session is not None:
            self._session.close()

    # stats, read back after the run

    @property
    def memory_steps(self) -> int:
        return len(self._telemetry())

    @property
    def memory_tokens(self) -> int:
        return sum(e.get("tokens_in", 0) + e.get("tokens_out", 0) for e in self._telemetry())

    def _telemetry(self) -> list[dict[str, Any]]:
        path = self.state_dir / "telemetry.jsonl"
        return read_events(path) if path.exists() else []

    def _count(self, ctx: str | None) -> str | None:
        if ctx:
            self.interventions += 1
        return ctx


class _SessionStrategy(Strategy):
    """Shared setup for the conditions that keep a real bank."""

    def __init__(self, task: Task, state_dir: Path, memory_provider: Any = None) -> None:
        super().__init__(task, state_dir, memory_provider)
        config = AgentMemConfig(state_dir=str(state_dir), max_tool_rounds=1)
        self._session = MemorySession(
            task=task.description,
            config=config,
            provider=memory_provider,
            session_id=task.id,
            async_worker=False,
        )

    def observe(self, events: list[Event]) -> None:
        assert self._session is not None
        self._session.observe(events)


class AgentMemStrategy(_SessionStrategy):
    name = "agentmem"

    def context(self) -> str | None:
        assert self._session is not None
        return self._count(self._session.pending_context())


class FullBankStrategy(_SessionStrategy):
    name = "full_bank"

    def context(self) -> str | None:
        assert self._session is not None
        bank = self._session.bank
        if bank.is_empty():
            return None
        return self._count("[AgentMem full bank]\n" + bank.render_for_agent())


class AlwaysInjectStrategy(_SessionStrategy):
    name = "always_inject"

    def context(self) -> str | None:
        assert self._session is not None
        entries = self._session.bank.all_entries()
        if not entries:
            return None
        latest = max(entries, key=lambda e: e.updated_step)
        return self._count(f"[AgentMem] {latest.render()}")


class InjectionOnlyStrategy(Strategy):
    """No bank, just a generic advisory after a failure. Grounded in nothing, so it
    can only ever be a weak nudge."""

    name = "injection_only"

    def __init__(self, task: Task, state_dir: Path, memory_provider: Any = None) -> None:
        super().__init__(task, state_dir, memory_provider)
        self._last_failed = False

    def context(self) -> str | None:
        if self._last_failed:
            return self._count("[AgentMem] That last step failed — reconsider before repeating it.")
        return None

    def observe(self, events: list[Event]) -> None:
        self._last_failed = any(e.kind == "tool_result" and not e.ok for e in events)


_REGISTRY: dict[str, type[Strategy]] = {
    "baseline": Strategy,
    "agentmem": AgentMemStrategy,
    "full_bank": FullBankStrategy,
    "always_inject": AlwaysInjectStrategy,
    "injection_only": InjectionOnlyStrategy,
}

CONDITIONS = list(_REGISTRY.keys())


def build_strategy(name: str, task: Task, state_dir: Path, memory_provider: Any = None) -> Strategy:
    try:
        cls = _REGISTRY[name]
    except KeyError:
        raise ValueError(f"Unknown condition {name!r}; pick from {CONDITIONS}") from None
    return cls(task, state_dir, memory_provider)
