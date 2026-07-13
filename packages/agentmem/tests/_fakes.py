"""Test doubles, importable from any test module.

Kept out of conftest.py so tests can ``from _fakes import FakeProvider`` explicitly
rather than leaning on conftest's implicit-plugin import.
"""

from __future__ import annotations

from agentmem.llm.base import LLMResponse
from agentmem.schemas import TokenUsage
from agentmem.tools import ToolCall


class FakeProvider:
    """Pops canned responses. Phase 1 calls (which carry `tools`) and Phase 2 calls
    draw from separate scripts; running dry yields a safe default (no edits, no
    intervention), which is also correct for an exhausted script."""

    model = "fake-model"

    def __init__(
        self,
        phase1: list[LLMResponse] | None = None,
        phase2: list[LLMResponse] | None = None,
    ) -> None:
        self.phase1 = list(phase1 or [])
        self.phase2 = list(phase2 or [])
        self.seen: list[str] = []

    def complete(self, *, system, messages, tools=None, max_tokens=1024):  # noqa: ANN001
        if tools:
            self.seen.append("phase1")
            return (
                self.phase1.pop(0)
                if self.phase1
                else LLMResponse(usage=TokenUsage(model=self.model))
            )
        self.seen.append("phase2")
        if self.phase2:
            return self.phase2.pop(0)
        return LLMResponse(text="<no_intervention/>", usage=TokenUsage(model=self.model))


def tool_response(*calls: ToolCall) -> LLMResponse:
    return LLMResponse(tool_calls=list(calls), usage=TokenUsage(model="fake-model"))


def text_response(text: str) -> LLMResponse:
    return LLMResponse(text=text, usage=TokenUsage(model="fake-model"))


def call(name: str, block_id: str = "toolu_1", **args: object) -> ToolCall:
    return ToolCall(name=name, args=args, block_id=block_id)
