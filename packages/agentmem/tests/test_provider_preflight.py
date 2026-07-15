"""preflight() catches an unusable provider config before a memory-step swallows it."""

from __future__ import annotations

import sys

import pytest
from agentmem.config import AgentMemConfig
from agentmem.llm import preflight


def hide_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `import litellm` fail whether or not the extra is installed, so the
    not-installed path is tested the same way on every machine."""
    monkeypatch.setitem(sys.modules, "litellm", None)


def test_flags_a_litellm_model(monkeypatch: pytest.MonkeyPatch) -> None:
    hide_litellm(monkeypatch)
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
