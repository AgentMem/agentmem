"""Adapter for the Claude Agent SDK (in-process hooks)."""

from __future__ import annotations

from typing import Any

from ..session import MemorySession
from .claude_code import events_from_tool_use, hook_output, response_indicates_error


class MemoryHooks:
    """The PostToolUse callback bound to a MemorySession.

    The signature matches the SDK's `(input_data, tool_use_id, context)`, but only
    `input_data` is used, so it's trivial to call in a test.
    """

    def __init__(self, session: MemorySession) -> None:
        self.session = session

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
    """Register AgentMem's PostToolUse hook on a ClaudeAgentOptions and return it.

    We never touch the user's tools or system prompt, only add a hook. The live session
    is stored on `options.agentmem_session` so callers can inspect or close it.
    """
    try:
        from claude_agent_sdk import HookMatcher  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised only without the SDK
        raise ImportError(
            "The Claude Agent SDK isn't installed. Run: pip install 'agentmem-core[agent-sdk]'"
        ) from exc

    session = session or MemorySession(task=task, **session_kwargs)
    hooks = MemoryHooks(session)

    registry = getattr(options, "hooks", None)
    if not isinstance(registry, dict):
        registry = {}
    registry.setdefault("PostToolUse", []).append(HookMatcher(hooks=[hooks.on_post_tool]))

    options.hooks = registry
    options.agentmem_session = session
    return options
