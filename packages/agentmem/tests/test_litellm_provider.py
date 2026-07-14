"""The litellm provider's Anthropic<->OpenAI translation, offline (no litellm needed for
the pure helpers; a fake module stands in for the network call)."""

from __future__ import annotations

import types

import pytest
from agentmem.llm import litellm as lp
from agentmem.llm.base import LLMResponse


def test_tools_translate_to_openai_function_shape() -> None:
    anthropic = [
        {"name": "memory_write", "description": "save", "input_schema": {"type": "object"}}
    ]
    out = lp._to_openai_tools(anthropic)
    assert out == [
        {
            "type": "function",
            "function": {
                "name": "memory_write",
                "description": "save",
                "parameters": {"type": "object"},
            },
        }
    ]


def test_messages_translate_string_turns_and_prepend_system() -> None:
    out = lp._to_openai_messages("SYS", [{"role": "user", "content": "hello"}])
    assert out == [{"role": "system", "content": "SYS"}, {"role": "user", "content": "hello"}]


def test_assistant_tool_use_becomes_openai_tool_calls() -> None:
    turn = {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "saving"},
            {"type": "tool_use", "id": "tu_1", "name": "memory_write", "input": {"content": "x"}},
        ],
    }
    out = lp._to_openai_messages("SYS", [turn])
    asst = out[1]
    assert asst["role"] == "assistant" and asst["content"] == "saving"
    assert asst["tool_calls"][0]["id"] == "tu_1"
    assert asst["tool_calls"][0]["function"]["name"] == "memory_write"
    assert asst["tool_calls"][0]["function"]["arguments"] == '{"content": "x"}'


def test_tool_result_turn_expands_to_tool_role_messages() -> None:
    turn = {
        "role": "user",
        "content": [
            {"type": "tool_result", "tool_use_id": "tu_1", "content": "Saved as K-001."},
            {"type": "tool_result", "tool_use_id": "tu_2", "content": "Updated K-002."},
        ],
    }
    out = lp._to_openai_messages("SYS", [turn])[1:]  # drop the system message
    assert out == [
        {"role": "tool", "tool_call_id": "tu_1", "content": "Saved as K-001."},
        {"role": "tool", "tool_call_id": "tu_2", "content": "Updated K-002."},
    ]


def test_parse_args_handles_dict_json_and_garbage() -> None:
    assert lp._parse_args({"a": 1}) == {"a": 1}
    assert lp._parse_args('{"a": 1}') == {"a": 1}
    assert lp._parse_args("not json") == {}
    assert lp._parse_args(None) == {}


def _fake_response(content: str | None, tool_calls: list[dict] | None = None) -> object:
    message = types.SimpleNamespace(
        content=content,
        tool_calls=[
            types.SimpleNamespace(
                id=tc["id"],
                function=types.SimpleNamespace(name=tc["name"], arguments=tc["arguments"]),
            )
            for tc in (tool_calls or [])
        ],
    )
    choice = types.SimpleNamespace(
        message=message, finish_reason="tool_calls" if tool_calls else "stop"
    )
    usage = types.SimpleNamespace(prompt_tokens=12, completion_tokens=7)
    return types.SimpleNamespace(choices=[choice], usage=usage)


def test_response_translates_text_tool_calls_and_usage() -> None:
    resp = _fake_response(
        "done", [{"id": "tc_9", "name": "memory_write", "arguments": '{"content": "y"}'}]
    )
    out = lp._from_openai_response(resp, model="gemini/gemini-2.5-flash", latency_ms=1.0)
    assert isinstance(out, LLMResponse)
    assert out.text == "done"
    assert out.tool_calls[0].name == "memory_write"
    assert out.tool_calls[0].args == {"content": "y"}
    assert out.tool_calls[0].block_id == "tc_9"
    assert out.usage.input_tokens == 12 and out.usage.output_tokens == 7
    assert out.usage.model == "gemini/gemini-2.5-flash"


def test_complete_wires_translation_through_a_fake_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict = {}

    def fake_completion(**kwargs: object) -> object:
        seen.update(kwargs)
        return _fake_response("all set")

    monkeypatch.setitem(
        __import__("sys").modules, "litellm", types.SimpleNamespace(completion=fake_completion)
    )

    provider = lp.LiteLLMProvider(model="gemini/gemini-2.5-flash")
    out = provider.complete(
        system="SYS",
        messages=[{"role": "user", "content": "go"}],
        tools=[{"name": "memory_write", "description": "save", "input_schema": {"type": "object"}}],
        max_tokens=256,
    )
    assert out.text == "all set"
    assert seen["model"] == "gemini/gemini-2.5-flash"
    assert seen["max_tokens"] == 256
    assert seen["messages"][0] == {"role": "system", "content": "SYS"}
    assert seen["tools"][0]["type"] == "function"


def test_response_with_no_choices_is_an_empty_turn() -> None:
    # Gemini returns an empty choices list on a safety/recitation block; don't crash.
    resp = types.SimpleNamespace(
        choices=[], usage=types.SimpleNamespace(prompt_tokens=5, completion_tokens=0)
    )
    out = lp._from_openai_response(resp, model="gemini/gemini-2.5-flash", latency_ms=1.0)
    assert out.text == "" and out.tool_calls == [] and out.stop_reason == "empty"
    assert out.usage.input_tokens == 5


def test_retry_delay_prefers_the_servers_hint() -> None:
    assert lp._retry_delay(Exception("Please retry in 12.5s."), 0) == 13.5
    assert lp._retry_delay(Exception("no hint"), 0) == 5.0
    assert lp._retry_delay(Exception("no hint"), 3) == 40.0
    assert lp._retry_delay(Exception("retry in 999s"), 0) == 65.0  # capped


def test_is_retryable_matches_rate_limits_and_5xx() -> None:
    class ServiceUnavailableError(Exception):
        pass

    class BadRequestError(Exception):
        pass

    assert lp._is_retryable(ServiceUnavailableError("high demand"))
    err503 = Exception("x")
    err503.status_code = 503  # type: ignore[attr-defined]
    assert lp._is_retryable(err503)
    assert not lp._is_retryable(BadRequestError("bad schema"))
    err400 = Exception("x")
    err400.status_code = 400  # type: ignore[attr-defined]
    assert not lp._is_retryable(err400)


def test_complete_retries_a_transient_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # class name must be one _is_retryable recognizes
    class RateLimitError(Exception):
        pass

    calls = {"n": 0}

    def fake_completion(**_: object) -> object:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateLimitError("Please retry in 0.01s.")
        return _fake_response("recovered")

    monkeypatch.setitem(
        __import__("sys").modules, "litellm", types.SimpleNamespace(completion=fake_completion)
    )
    monkeypatch.setattr(lp.time, "sleep", lambda _: None)  # don't actually wait

    provider = lp.LiteLLMProvider(model="gemini/gemini-2.5-flash", max_retries=3)
    out = provider.complete(system="s", messages=[{"role": "user", "content": "hi"}])
    assert out.text == "recovered" and calls["n"] == 2


def test_complete_reraises_a_non_retryable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class BadRequestError(Exception):
        pass

    def boom(**_: object) -> object:
        raise BadRequestError("bad tool schema")

    monkeypatch.setitem(
        __import__("sys").modules, "litellm", types.SimpleNamespace(completion=boom)
    )
    provider = lp.LiteLLMProvider(model="gemini/gemini-2.5-flash", max_retries=3)
    with pytest.raises(BadRequestError):
        provider.complete(system="s", messages=[{"role": "user", "content": "hi"}])
