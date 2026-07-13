"""Provider selection."""

from __future__ import annotations

from ..config import AgentMemConfig
from .base import LLMProvider, LLMResponse

__all__ = ["LLMProvider", "LLMResponse", "make_provider"]


def make_provider(config: AgentMemConfig) -> LLMProvider:
    model = config.model
    # "litellm/..." opts into the extra; everything else goes to Anthropic.
    if model.startswith("litellm/"):
        from .litellm import LiteLLMProvider

        return LiteLLMProvider(model=model.removeprefix("litellm/"))

    from .anthropic import AnthropicProvider

    return AnthropicProvider(
        model=model,
        api_key=config.api_key,
        timeout=config.request_timeout_s,
    )
