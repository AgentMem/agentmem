"""Adapter for the OpenAI Agents SDK (`openai-agents`).

The SDK is fully hook-instrumented, so this leaves the developer's Agent, tools, and
instructions untouched and works through the two documented seams:

- OBSERVE: a `RunHooks` subclass reads the trajectory as it happens (new input messages
  at each model call, tool results, the final output) and feeds it back.
- INJECT (transient): `RunConfig.call_model_input_filter` runs right before every model
  call and edits the input in-flight. What it returns is used for that one call and is
  never written back to session history, so a reminder is consumed once, matching
  AgentMem's contract. The base `instructions` are passed through unchanged.

Both seams share one object you pass as `Runner.run(..., context=...)`: the hooks stash a
pending reminder on it, the filter reads and clears it. Verified against `openai-agents`
0.18.2.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..schemas import Event
from ..session import MemorySession

_MAX_RESULT_CHARS = 2000
_FAILURE_MARKERS = ("traceback", "error:", "exception", "failed", "assertionerror", "fatal")


@dataclass
class MemoryContext:
    """The run context AgentMem threads through the SDK. Pass it as
    `Runner.run(..., context=ctx)`; stash your own state on `data`."""

    session: MemorySession
    data: Any = None
    pending_reminder: str | None = None
    _seen_input: int = field(default=0, repr=False)


def _item_field(item: Any, name: str) -> Any:
    """Read a field from an SDK input item, whether it's a dict or an object."""
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def _message_events(input_items: list[Any], start: int) -> list[Event]:
    """Turn input items past `start` into message events, keeping only user/assistant
    turns with text content (tool-call plumbing is observed separately)."""
    events: list[Event] = []
    for item in input_items[start:]:
        role = _item_field(item, "role")
        content = _item_field(item, "content")
        if role in ("user", "assistant") and isinstance(content, str) and content:
            events.append(Event(kind="message", role=role, text=content))
    return events


def _looks_failed(text: str) -> bool:
    """A tool result rarely reports success/failure structurally, so fall back to the
    error words a coding tool prints. This drives the failure trigger; the memory agent
    reads the text regardless."""
    low = text.lower()
    return any(marker in low for marker in _FAILURE_MARKERS)


def _tool_event(tool_name: str, result: Any) -> Event:
    text = str(result)
    ok = not _looks_failed(text)
    if len(text) > _MAX_RESULT_CHARS:
        text = text[:_MAX_RESULT_CHARS] + " [...]"
    return Event(kind="tool_result", tool_name=tool_name, ok=ok, text=text)


def apply_reminder(model_input: list[Any], reminder: str | None) -> list[Any]:
    """Return the model input with a transient reminder appended, or unchanged if there
    is none. A developer-role message reads as an instruction-like nudge."""
    if not reminder:
        return model_input
    return [*model_input, {"role": "developer", "content": reminder}]


def _observe_and_stage(ctx: MemoryContext, events: list[Event]) -> None:
    if events:
        ctx.session.observe(events)
    ctx.pending_reminder = ctx.session.pending_context() or ctx.pending_reminder


class OpenAIMemory:
    """What you plug into a run: `context`, `hooks`, and `run_config`. Use them as
    `Runner.run(agent, input, context=mem.context, hooks=mem.hooks, run_config=mem.run_config)`."""

    def __init__(self, context: MemoryContext, hooks: Any, run_config: Any) -> None:
        self.context = context
        self.hooks = hooks
        self.run_config = run_config

    @property
    def session(self) -> MemorySession:
        return self.context.session

    def close(self) -> None:
        self.context.session.close()

    def __enter__(self) -> OpenAIMemory:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def attach_memory(
    *,
    task: str,
    session: MemorySession | None = None,
    data: Any = None,
    session_kwargs: dict[str, Any] | None = None,
) -> OpenAIMemory:
    """Build the hooks, run config, and context for a memory-backed run. Import happens
    here so `import agentmem.integrations.openai_agents` works without the SDK."""
    try:
        from agents import RunConfig, RunHooks
        from agents.run_config import ModelInputData
    except ImportError as exc:  # pragma: no cover - only without the SDK installed
        raise ImportError(
            "The OpenAI Agents SDK isn't installed. Run: pip install 'agentmem[openai-agents]'"
        ) from exc

    session = session or MemorySession(task=task, **(session_kwargs or {}))
    context = MemoryContext(session=session, data=data)

    class _Hooks(RunHooks):
        async def on_llm_start(
            self, ctx: Any, agent: Any, system_prompt: Any, input_items: list[Any]
        ) -> None:
            mc: MemoryContext = ctx.context
            events = _message_events(input_items, mc._seen_input)
            mc._seen_input = len(input_items)
            _observe_and_stage(mc, events)

        async def on_tool_end(self, ctx: Any, agent: Any, tool: Any, result: Any) -> None:
            mc: MemoryContext = ctx.context
            _observe_and_stage(mc, [_tool_event(getattr(tool, "name", "tool"), result)])

        async def on_agent_end(self, ctx: Any, agent: Any, output: Any) -> None:
            mc: MemoryContext = ctx.context
            if output:
                _observe_and_stage(mc, [Event(kind="message", role="assistant", text=str(output))])

    def _filter(data: Any) -> Any:
        mc: MemoryContext | None = getattr(data, "context", None)
        reminder = mc.pending_reminder if mc else None
        if not reminder or mc is None:
            return data.model_data
        mc.pending_reminder = None  # consumed once
        return ModelInputData(
            input=apply_reminder(data.model_data.input, reminder),
            instructions=data.model_data.instructions,
        )

    return OpenAIMemory(context, _Hooks(), RunConfig(call_model_input_filter=_filter))
