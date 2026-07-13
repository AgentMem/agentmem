"""Adapter for the Claude Agent SDK (in-process hooks).

The SDK exposes hooks much like Claude Code, so the callbacks here reuse the same
payload-translation helpers. `MemoryHooks` holds the callback logic (and is what the
tests exercise directly); `attach_memory` wires those callbacks onto a
`ClaudeAgentOptions` and hands back the options plus the session.

The exact hook-registration shape has moved between SDK versions, so `attach_memory`
keeps that wiring minimal and easy to adjust; the behavior it wires up is fully
tested via `MemoryHooks`.
"""

from __future__ import annotations

from typing import Any

from ..session import MemorySession
from .claude_code import (
    event_from_prompt,
    events_from_tool_use,
    hook_output,
    response_indicates_error,
)


class MemoryHooks:
    """Hook callbacks bound to a MemorySession.

    The signatures match the SDK's `(input_data, tool_use_id, context)` shape, but
    only `input_data` is used, so they're trivial to call in a test.
    """

    def __init__(self, session: MemorySession) -> None:
        self.session = session

    async def on_user_prompt(
        self, input_data: dict[str, Any], tool_use_id: Any = None, context: Any = None
    ) -> dict[str, Any]:
        # Read the pending reminder before observing the new prompt.
        reminder = self.session.pending_context()
        prompt = str(input_data.get("prompt") or "")
        if prompt:
            self.session.observe([event_from_prompt(prompt)])
        return hook_output("UserPromptSubmit", reminder)

    async def on_post_tool(
        self, input_data: dict[str, Any], tool_use_id: Any = None, context: Any = None
    ) -> dict[str, Any]:
        tool_name = str(input_data.get("tool_name") or "tool")
        tool_input = input_data.get("tool_input")
        tool_response = input_data.get("tool_response")
        ok = not response_indicates_error(tool_response)
        self.session.observe(events_from_tool_use(tool_name, tool_input, tool_response, ok=ok))
        return hook_output("PostToolUse", self.session.pending_context())


def attach_memory(
    options: Any,
    *,
    task: str,
    session: MemorySession | None = None,
    **session_kwargs: Any,
) -> Any:
    """Register AgentMem's hooks on a ClaudeAgentOptions and return it.

    We never touch the user's tools or system prompt — only add hooks. The live
    session is stored on `options.agentmem_session` so callers can inspect or close it.
    """
    session = session or MemorySession(task=task, **session_kwargs)
    hooks = MemoryHooks(session)

    registry = getattr(options, "hooks", None)
    if not isinstance(registry, dict):
        registry = {}
    registry.setdefault("UserPromptSubmit", []).append(hooks.on_user_prompt)
    registry.setdefault("PostToolUse", []).append(hooks.on_post_tool)

    options.hooks = registry
    options.agentmem_session = session
    return options
