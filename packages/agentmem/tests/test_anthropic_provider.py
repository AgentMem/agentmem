"""AnthropicProvider tests against a mocked Messages endpoint.

respx intercepts the HTTP call, so this checks we parse the real response shape (text
+ tool_use blocks + usage) without a key or a network. This is the pattern for any
future "does the wire format still match" test.
"""

from __future__ import annotations

import httpx
import respx
from agentmem.llm.anthropic import AnthropicProvider
from agentmem.tools import TOOL_SCHEMAS

_MESSAGES_URL = "https://api.anthropic.com/v1/messages"


def _response_body() -> dict:
    return {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-4-5",
        "content": [
            {"type": "text", "text": "Saving that."},
            {
                "type": "tool_use",
                "id": "toolu_01",
                "name": "memory_save_knowledge",
                "input": {"tag": "env", "content": "python 3.11"},
            },
        ],
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {"input_tokens": 123, "output_tokens": 45},
    }


@respx.mock
def test_parses_text_tool_use_and_usage() -> None:
    route = respx.post(_MESSAGES_URL).mock(return_value=httpx.Response(200, json=_response_body()))

    provider = AnthropicProvider(model="claude-haiku-4-5", api_key="test-key")
    resp = provider.complete(
        system="you are the memory manager",
        messages=[{"role": "user", "content": "hi"}],
        tools=TOOL_SCHEMAS,
    )

    assert route.called
    assert resp.text == "Saving that."
    assert len(resp.tool_calls) == 1
    call = resp.tool_calls[0]
    assert call.name == "memory_save_knowledge"
    assert call.args == {"tag": "env", "content": "python 3.11"}
    assert call.block_id == "toolu_01"
    assert resp.usage.input_tokens == 123
    assert resp.usage.output_tokens == 45
    assert resp.usage.model == "claude-haiku-4-5"


@respx.mock
def test_no_tools_when_none_passed() -> None:
    route = respx.post(_MESSAGES_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "msg_02",
                "type": "message",
                "role": "assistant",
                "model": "claude-haiku-4-5",
                "content": [{"type": "text", "text": "<no_intervention/>"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 50, "output_tokens": 8},
            },
        )
    )

    provider = AnthropicProvider(model="claude-haiku-4-5", api_key="test-key")
    resp = provider.complete(system="s", messages=[{"role": "user", "content": "x"}])

    assert route.called
    assert resp.tool_calls == []
    assert resp.text == "<no_intervention/>"
    # Phase 2 sends no tools; the request body should carry none either.
    assert "tools" not in respx.calls.last.request.content.decode()
