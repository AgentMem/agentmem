"""preflight() catches an unusable provider config before a memory-step swallows it."""

from __future__ import annotations

import pytest
from agentmem.config import AgentMemConfig
from agentmem.llm import preflight


def test_flags_a_litellm_model() -> None:
    problems = preflight(AgentMemConfig(model="litellm/gpt-4o"))
    assert problems and "litellm" in problems[0]


def test_flags_a_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    problems = preflight(AgentMemConfig(model="claude-haiku-4-5", api_key=None))
    assert problems and "ANTHROPIC_API_KEY" in problems[0]


def test_ok_with_an_explicit_key() -> None:
    assert preflight(AgentMemConfig(model="claude-haiku-4-5", api_key="sk-ant-test")) == []


def test_ok_with_an_env_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert preflight(AgentMemConfig(model="claude-haiku-4-5", api_key=None)) == []
