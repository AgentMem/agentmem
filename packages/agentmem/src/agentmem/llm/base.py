"""The provider interface.

Everything the memory agent needs from an LLM goes through one method, `complete`.
Phase 1 passes `tools`; Phase 2 doesn't. A small surface keeps the provider swappable
(Anthropic today, others later).

Messages are Anthropic-native content-block dicts, since the Phase 1 tool loop needs
tool_use / tool_result blocks. A non-Anthropic provider would translate at its edge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from ..schemas import TokenUsage
from ..tools import ToolCall


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    stop_reason: str = ""
    raw_assistant_content: Any = None  # provider's raw turn, kept for debugging


class LLMProvider(Protocol):
    model: str

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Run one turn. Blocking; the caller runs it off the hot path."""
        ...
