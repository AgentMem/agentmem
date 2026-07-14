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
        try:
            import litellm  # noqa: F401
        except ImportError:
            return [
                "model uses a litellm/ backend but litellm isn't installed; "
                "run: pip install 'agentmem[litellm]'"
            ]
        # The backend's own key (GEMINI_API_KEY, OPENAI_API_KEY, ...) is litellm's to
        # read and validate; we can't tell which one this model needs from here.
        return []
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
