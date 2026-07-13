"""litellm provider: the path to non-Anthropic models. Not implemented yet.

The catch is that our messages are Anthropic-native content blocks while litellm
speaks OpenAI's tool-call format, so this adapter is where that translation goes.
Optional extra: `pip install agentmem[litellm]`.
"""

from __future__ import annotations

from typing import Any

from .base import LLMResponse


class LiteLLMProvider:
    def __init__(self, model: str, **_: Any) -> None:
        self.model = model

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        raise NotImplementedError(
            "The litellm provider isn't implemented yet. Use the default Anthropic "
            "provider, or open an issue if you need a specific backend."
        )
