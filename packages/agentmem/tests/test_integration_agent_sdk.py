"""Tests for the Claude Agent SDK adapter.

The PostToolUse callback runs against a real MemorySession (scripted provider, inline
steps), so this exercises the full observe -> step -> reminder path. `attach_memory`
needs the SDK's HookMatcher, which isn't a test dependency, so those tests stand in a
fake `claude_agent_sdk` module.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from agentmem import MemorySession
from agentmem._demo import ScriptedProvider
from agentmem.config import AgentMemConfig
from agentmem.integrations.claude_agent_sdk import MemoryHooks, attach_memory


def _session(tmp_path: Path) -> MemorySession:
    return MemorySession(
        task="fix the tests",
        config=AgentMemConfig(state_dir=str(tmp_path), max_tool_rounds=1),
        provider=ScriptedProvider(),
        session_id="sdk",
        async_worker=False,
    )


def _fake_sdk(monkeypatch: pytest.MonkeyPatch) -> type:
    module = types.ModuleType("claude_agent_sdk")

    class HookMatcher:
        def __init__(self, matcher: object = None, hooks: object = None, timeout: int = 60) -> None:
            self.matcher = matcher
            self.hooks = list(hooks or [])

    module.HookMatcher = HookMatcher  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", module)
    return HookMatcher


async def test_post_tool_flow_yields_reminder(tmp_path: Path) -> None:
    hooks = MemoryHooks(_session(tmp_path))
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "pytest"},
        "tool_response": {"exit_code": 1, "stdout": "FAILED"},
    }

    r1 = await hooks.on_post_tool(payload)
    assert r1 == {}  # first failure recorded, silent

    r2 = await hooks.on_post_tool(payload)
    assert "P-001" in r2["hookSpecificOutput"]["additionalContext"]


def test_attach_memory_wraps_the_callback_in_a_hookmatcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hook_matcher = _fake_sdk(monkeypatch)

    class FakeOptions:
        pass

    options = FakeOptions()
    returned = attach_memory(options, task="t", session=_session(tmp_path))

    assert returned is options
    entry = options.hooks["PostToolUse"][0]
    assert isinstance(entry, hook_matcher)  # a HookMatcher, not a bare callable
    assert callable(entry.hooks[0])
    assert options.agentmem_session is not None
    assert not hasattr(options, "tools")  # we never add or change tools


def test_attach_memory_preserves_existing_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_sdk(monkeypatch)

    class FakeOptions:
        def __init__(self) -> None:
            self.hooks = {"PostToolUse": ["someone-elses-hook"]}

    options = attach_memory(FakeOptions(), task="t", session=_session(tmp_path))
    assert "someone-elses-hook" in options.hooks["PostToolUse"]
    assert len(options.hooks["PostToolUse"]) == 2  # theirs + ours


def test_attach_memory_errors_clearly_without_the_sdk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)  # force the import to fail
    with pytest.raises(ImportError, match="pip install"):
        attach_memory(object(), task="t", session=_session(tmp_path))
