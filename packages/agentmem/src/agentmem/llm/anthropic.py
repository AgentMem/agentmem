"""Anthropic Messages API provider (the default).

No retries or backoff: a memory-step is best-effort, and the session treats any
exception as "skip this step, keep the old bank".
"""

from __future__ import annotations

import time
from typing import Any

from ..schemas import TokenUsage
from ..tools import ToolCall
from .base import LLMResponse


class AnthropicProvider:
    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        # Lazy import so `import agentmem` doesn't require the SDK be importable.
        import anthropic

        self.model = model
        # api_key=None => the SDK reads ANTHROPIC_API_KEY from the environment.
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout)

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "system": system,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools

        started = time.perf_counter()
        resp = self._client.messages.create(**kwargs)
        latency_ms = (time.perf_counter() - started) * 1000.0

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(name=block.name, args=dict(block.input), block_id=block.id)
                )

        usage = TokenUsage(
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            latency_ms=latency_ms,
            model=self.model,
        )
        return LLMResponse(
            text="\n".join(text_parts).strip(),
            tool_calls=tool_calls,
            usage=usage,
            stop_reason=resp.stop_reason or "",
            raw_assistant_content=resp.content,
        )
