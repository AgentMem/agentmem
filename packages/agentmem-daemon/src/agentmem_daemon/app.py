"""The FastAPI daemon: HTTP endpoints for Claude Code hooks."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from agentmem import MemorySession
from agentmem.config import AgentMemConfig
from agentmem.integrations.claude_code import (
    bank_digest,
    event_from_prompt,
    events_from_tool_use,
    hook_output,
    project_key,
    response_indicates_error,
)
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool

from . import __version__
from .registry import PLACEHOLDER_TASK, SessionFactory, SessionRegistry


def _default_factory(base_config: AgentMemConfig) -> SessionFactory:
    def factory(key: str, cwd: str, task: str) -> MemorySession:
        # Memory lives with the project, under <cwd>/.agentmem, so it's local and
        # travels with the repo.
        state_dir = str(Path(cwd) / ".agentmem") if cwd not in ("", ".") else base_config.state_dir
        config = base_config.with_overrides(state_dir=state_dir)
        return MemorySession(task=task, session_id=key, config=config, async_worker=True)

    return factory


def create_app(
    factory: SessionFactory | None = None,
    config: AgentMemConfig | None = None,
) -> FastAPI:
    cfg = config or AgentMemConfig()
    registry = SessionRegistry(factory or _default_factory(cfg))

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        registry.close_all()  # persist every session's bank on shutdown

    app = FastAPI(title="AgentMem daemon", version=__version__, lifespan=lifespan)
    app.state.registry = registry

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.post("/hook/session-start")
    async def session_start(request: Request) -> dict[str, Any]:
        # Opening a session hands back what earlier sessions on this project learned.
        body = await _read_json(request)
        cwd = str(body.get("cwd") or ".")
        mem = registry.get_or_create(project_key(cwd), cwd)
        return hook_output("SessionStart", bank_digest(mem.bank, project=mem.project_bank))

    @app.post("/hook/prompt")
    async def prompt(request: Request) -> dict[str, Any]:
        body = await _read_json(request)
        cwd = str(body.get("cwd") or ".")
        mem = registry.get_or_create(project_key(cwd), cwd)
        text = str(body.get("prompt") or "")

        # Read the pending reminder before observing the new prompt: it comes from
        # earlier steps and applies to the turn about to happen.
        reminder = mem.pending_context()
        if text:
            if mem.task == PLACEHOLDER_TASK:
                mem.task = text  # the first real prompt is the task
            mem.observe([event_from_prompt(text)])
        return hook_output("UserPromptSubmit", reminder)

    @app.post("/hook/post-tool")
    async def post_tool(request: Request) -> dict[str, Any]:
        return await _handle_tool(request, assume_ok=True)

    @app.post("/hook/tool-fail")
    async def tool_fail(request: Request) -> dict[str, Any]:
        return await _handle_tool(request, assume_ok=False)

    async def _handle_tool(request: Request, *, assume_ok: bool) -> dict[str, Any]:
        body = await _read_json(request)
        cwd = str(body.get("cwd") or ".")
        mem = registry.get_or_create(project_key(cwd), cwd)

        tool_name = str(body.get("tool_name") or body.get("toolName") or "tool")
        tool_input = body.get("tool_input", body.get("toolInput"))
        tool_response = body.get("tool_response", body.get("toolResponse"))
        ok = assume_ok and not response_indicates_error(tool_response)

        mem.observe(events_from_tool_use(tool_name, tool_input, tool_response, ok=ok))
        # A reminder cached by a prior step lands right after this tool result, which
        # is often the moment just before the agent repeats a mistake.
        return hook_output("PostToolUse", mem.pending_context())

    @app.post("/hook/pre-compact")
    async def pre_compact(request: Request) -> dict[str, Any]:
        # Force a synchronous step, then the merge/fusion pass, so execution state is
        # saved and the bank is tidied before the transcript gets compacted away.
        body = await _read_json(request)
        cwd = str(body.get("cwd") or ".")
        mem = registry.get_or_create(project_key(cwd), cwd)
        await run_in_threadpool(mem.tick, "pre_compact", consolidate=True)
        return {}

    @app.post("/hook/session-end")
    async def session_end(request: Request) -> dict[str, Any]:
        # end_session() only enqueues work onto the session's own background worker
        # (a plain queue.put, never blocking). The session stays alive for the next
        # SessionStart on this project, so this must NOT call close(). The actual
        # consolidation + grading run off the request path, same as any memory-step.
        body = await _read_json(request)
        cwd = str(body.get("cwd") or ".")
        mem = registry.get(project_key(cwd))
        if mem is not None:
            mem.end_session()
        return {}

    return app


async def _read_json(request: Request) -> dict[str, Any]:
    """Parse the hook body, tolerating an empty or malformed one.

    A hook must never fail just because a payload was odd; worst case we act on an
    empty dict and return nothing.
    """
    try:
        data = await request.json()
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}
