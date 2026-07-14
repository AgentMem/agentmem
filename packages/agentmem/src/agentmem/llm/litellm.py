"""litellm provider: the path to non-Anthropic models (Gemini, OpenAI, vLLM, Ollama).

Our messages are Anthropic-native content blocks while litellm speaks OpenAI's format, so
this adapter translates at the edge: Anthropic tool_use / tool_result blocks become OpenAI
tool_calls and tool-role messages on the way in, and the OpenAI response becomes an
`LLMResponse` on the way out. litellm handles OpenAI to the actual backend.

Set `model="litellm/<backend>"`, e.g. `litellm/gemini/gemini-2.5-flash` with `GEMINI_API_KEY`
set. Optional extra: `pip install 'agentmem[litellm]'`.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from ..schemas import TokenUsage
from ..tools import ToolCall
from .base import LLMResponse

_MAX_RETRY_DELAY = 65.0

# Transient errors worth retrying: rate limits and the 5xx family. Matched by class name
# and status code so we don't depend on which exceptions a given litellm version exports.
_RETRYABLE_NAMES = frozenset(
    {
        "RateLimitError",
        "ServiceUnavailableError",
        "InternalServerError",
        "APIConnectionError",
        "APIError",
        "Timeout",
    }
)
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


def _is_retryable(err: Exception) -> bool:
    if type(err).__name__ in _RETRYABLE_NAMES:
        return True
    return getattr(err, "status_code", None) in _RETRYABLE_STATUS


def _retry_delay(err: Exception, attempt: int) -> float:
    """How long to wait before retrying. Prefer the server's own 'retry in Ns' hint
    (Gemini's free tier sends one), else back off exponentially."""
    match = re.search(r"retry in ([\d.]+)s", str(err), re.I)
    if match:
        hint: float = float(match.group(1)) + 1.0
        return min(_MAX_RETRY_DELAY, hint)
    return min(_MAX_RETRY_DELAY, 5.0 * (2.0**attempt))


def _to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {}),
            },
        }
        for tool in tools
    ]


def _block_text(content: Any) -> str:
    """A tool_result's content is a plain string in our code, but Anthropic also allows a
    list of blocks; handle both."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return str(content)


def _to_openai_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate Anthropic-native turns to OpenAI's shape. Tool results, which Anthropic
    bundles into one user turn, expand into one tool-role message each."""
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for msg in messages:
        role = msg["role"]
        content = msg["content"]
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        tool_results: list[dict[str, Any]] = []
        for block in content:
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "tool_use":
                tool_calls.append(
                    {
                        "id": block["id"],
                        "type": "function",
                        "function": {
                            "name": block["name"],
                            "arguments": json.dumps(block.get("input", {})),
                        },
                    }
                )
            elif btype == "tool_result":
                tool_results.append(
                    {
                        "role": "tool",
                        "tool_call_id": block["tool_use_id"],
                        "content": _block_text(block.get("content", "")),
                    }
                )

        if role == "assistant":
            turn: dict[str, Any] = {
                "role": "assistant",
                "content": "\n".join(text_parts).strip() or None,
            }
            if tool_calls:
                turn["tool_calls"] = tool_calls
            out.append(turn)
        else:
            out.extend(tool_results)
            if text_parts:
                out.append({"role": "user", "content": "\n".join(text_parts).strip()})
    return out


def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _from_openai_response(resp: Any, model: str, latency_ms: float) -> LLMResponse:
    usage_obj = getattr(resp, "usage", None)
    usage = TokenUsage(
        input_tokens=getattr(usage_obj, "prompt_tokens", 0) or 0,
        output_tokens=getattr(usage_obj, "completion_tokens", 0) or 0,
        latency_ms=latency_ms,
        model=model,
    )

    choices = getattr(resp, "choices", None) or []
    if not choices:
        # Some backends (Gemini on a safety or recitation block) return no choices at all.
        # Treat it as an empty turn: Phase 1 sees no tool calls and stops, Phase 2 falls
        # back to silence. Better a skipped memory-step than a crashed one.
        return LLMResponse(usage=usage, stop_reason="empty")

    choice = choices[0]
    message = choice.message
    tool_calls: list[ToolCall] = []
    for tc in getattr(message, "tool_calls", None) or []:
        tool_calls.append(
            ToolCall(name=tc.function.name, args=_parse_args(tc.function.arguments), block_id=tc.id)
        )
    return LLMResponse(
        text=(message.content or "").strip(),
        tool_calls=tool_calls,
        usage=usage,
        stop_reason=getattr(choice, "finish_reason", "") or "",
        raw_assistant_content=message,
    )


class LiteLLMProvider:
    def __init__(self, model: str, *, max_retries: int = 2, **_: Any) -> None:
        self.model = model
        # Free tiers rate-limit hard (Gemini's is 5 requests/minute) and 5xx under load,
        # so unlike the Anthropic provider this one retries transient errors rather than
        # losing the whole memory-step. Non-transient errors still propagate.
        self.max_retries = max_retries

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        try:
            from litellm import completion
        except ImportError as exc:  # pragma: no cover - only without litellm installed
            raise ImportError(
                "litellm isn't installed. Run: pip install 'agentmem[litellm]'"
            ) from exc

        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": _to_openai_messages(system, messages),
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = _to_openai_tools(tools)

        started = time.perf_counter()
        resp = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = completion(**kwargs)
                break
            except Exception as err:
                if attempt >= self.max_retries or not _is_retryable(err):
                    raise
                time.sleep(_retry_delay(err, attempt))
        latency_ms = (time.perf_counter() - started) * 1000.0
        return _from_openai_response(resp, self.model, latency_ms)
