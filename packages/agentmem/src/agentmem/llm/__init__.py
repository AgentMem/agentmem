"""Provider selection."""

from __future__ import annotations

import os

from ..config import AgentMemConfig
from .base import LLMProvider, LLMResponse

__all__ = ["LLMProvider", "LLMResponse", "make_provider", "preflight"]


def preflight(config: AgentMemConfig) -> list[str]:
    """Config problems that would stop a real memory-step from working, in plain
    English. Empty means the provider is ready. Callers surface this up front (the
    daemon at startup, `agentmem doctor`, a sync session at construction) so a missing
    key or an unsupported model is caught before it disappears into a memory-step."""
    if config.model.startswith("litellm/"):
        return [
            "model is set to a litellm/ backend, which isn't implemented yet; "
            "use an Anthropic model such as claude-haiku-4-5"
        ]
    if config.api_key is None and not os.environ.get("ANTHROPIC_API_KEY"):
        return ["ANTHROPIC_API_KEY is not set; export it, or pass api_key / config.api_key"]
    return []


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
