"""Tests for the Claude Agent SDK adapter.

The hook callbacks are async and run against a real MemorySession (scripted provider,
inline steps), so this exercises the full observe -> step -> reminder path through the
callbacks.
"""

from __future__ import annotations

from pathlib import Path

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


async def test_user_prompt_observes_and_upgrades_task(tmp_path: Path) -> None:
    session = _session(tmp_path)
    hooks = MemoryHooks(session)

    result = await hooks.on_user_prompt({"prompt": "make the suite pass"})
    assert result == {}  # nothing pending on the first prompt
    assert session.bank.version >= 1  # observing the prompt ran a step


def test_attach_memory_registers_hooks_without_touching_tools(tmp_path: Path) -> None:
    class FakeOptions:
        pass

    options = FakeOptions()
    returned = attach_memory(options, task="t", session=_session(tmp_path))

    assert returned is options
    assert callable(options.hooks["PostToolUse"][0])
    assert callable(options.hooks["UserPromptSubmit"][0])
    assert options.agentmem_session is not None
    assert not hasattr(options, "tools")  # we never add or change tools


def test_attach_memory_preserves_existing_hooks(tmp_path: Path) -> None:
    class FakeOptions:
        def __init__(self) -> None:
            self.hooks = {"PostToolUse": ["someone-elses-hook"]}

    options = attach_memory(FakeOptions(), task="t", session=_session(tmp_path))
    assert "someone-elses-hook" in options.hooks["PostToolUse"]
    assert len(options.hooks["PostToolUse"]) == 2  # theirs + ours
