"""Adapter for Aider (the terminal coding agent)."""

from __future__ import annotations

from typing import Any

from ..schemas import Event
from ..session import MemorySession

_EDIT_FORMAT_TO_MODULE = {
    "diff": ("editblock_coder", "EditBlockCoder"),
    "whole": ("wholefile_coder", "WholeFileCoder"),
    "ask": ("ask_coder", "AskCoder"),
}


def _append_reminder(chunks: Any, reminder: str) -> Any:
    """Append a transient system reminder to a ChatChunks. `chunks.reminder` is a fresh
    per-request list, so this reaches the model but never persists to Aider's history."""
    chunks.reminder = [*chunks.reminder, {"role": "system", "content": reminder}]
    return chunks


def make_memory_coder(main_model: Any, io: Any, *, edit_format: str = "diff", **kwargs: Any) -> Any:
    """Build an Aider coder of the given edit format, subclassed to carry a one-shot
    reminder. Set `coder.agentmem_reminder` before a turn; it's injected and cleared."""
    module_name, class_name = _EDIT_FORMAT_TO_MODULE.get(
        edit_format, _EDIT_FORMAT_TO_MODULE["diff"]
    )
    try:
        import importlib

        base = getattr(importlib.import_module(f"aider.coders.{module_name}"), class_name)
    except ImportError as exc:  # pragma: no cover - only without aider installed
        raise ImportError("Aider isn't installed. Run: pip install 'agentmem-core[aider]'") from exc

    class MemoryCoder(base):  # type: ignore[valid-type, misc]  # base resolved at runtime
        agentmem_reminder: str | None = None

        def format_chat_chunks(self) -> Any:
            chunks = super().format_chat_chunks()
            if self.agentmem_reminder:
                _append_reminder(chunks, self.agentmem_reminder)
                self.agentmem_reminder = None  # consumed once, even across reflections
            return chunks

    return MemoryCoder(main_model, io, **kwargs)


def _events_from_turn(user_message: str, reply: Any, coder: Any) -> list[Event]:
    events = [Event(kind="message", role="user", text=user_message)]
    if reply:
        events.append(Event(kind="message", role="assistant", text=str(reply)))
    for path in sorted(getattr(coder, "aider_edited_files", None) or []):
        events.append(Event(kind="tool_call", tool_name="edit", text=str(path)))
    for name in ("test", "lint"):
        outcome = getattr(coder, f"{name}_outcome", None)
        if outcome is not None:
            events.append(
                Event(
                    kind="tool_result",
                    tool_name=name,
                    ok=bool(outcome),
                    text=f"{name} {'passed' if outcome else 'failed'}",
                )
            )
    return events


class AiderMemory:
    """Drives an Aider coder with memory: inject the pending reminder before a turn,
    observe what the turn produced after. `coder` must come from `make_memory_coder`."""

    def __init__(self, session: MemorySession, coder: Any) -> None:
        self.session = session
        self.coder = coder

    def run(self, user_message: str, **run_kwargs: Any) -> Any:
        self.coder.agentmem_reminder = self.session.pending_context()
        reply = self.coder.run(with_message=user_message, **run_kwargs)
        self.session.observe(_events_from_turn(user_message, reply, self.coder))
        return reply

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> AiderMemory:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def attach_memory(
    main_model: Any,
    io: Any,
    *,
    task: str,
    session: MemorySession | None = None,
    edit_format: str = "diff",
    session_kwargs: dict[str, Any] | None = None,
    **coder_kwargs: Any,
) -> AiderMemory:
    """Build a memory-backed Aider coder in one call. `main_model` and `io` are Aider's
    `Model` and `InputOutput`; `coder_kwargs` (e.g. `fnames=`, `test_cmd=`) pass through."""
    session = session or MemorySession(task=task, **(session_kwargs or {}))
    coder = make_memory_coder(main_model, io, edit_format=edit_format, **coder_kwargs)
    return AiderMemory(session, coder)
