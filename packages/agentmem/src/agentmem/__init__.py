"""AgentMem: a proactive memory layer for long-horizon coding agents.

The public surface is small: construct a `MemorySession`, read `pending_context()`
before each agent turn, feed new events to `observe()`. Everything else may change
before 0.1.0.
"""

from __future__ import annotations

from . import triggers
from .config import AgentMemConfig
from .schemas import EntryLifecycle, Event, Intervention, MemoryBank, MemoryEntry, StepResult
from .session import MemorySession
from .wrapper import wrap

__all__ = [
    "MemorySession",
    "wrap",
    "triggers",
    "AgentMemConfig",
    "Event",
    "MemoryBank",
    "MemoryEntry",
    "EntryLifecycle",
    "Intervention",
    "StepResult",
]

__version__ = "0.1.0"
