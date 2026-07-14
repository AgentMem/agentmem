"""Daemon-less command-hook runtime."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .config import AgentMemConfig
from .integrations.claude_code import (
    bank_digest,
    event_from_prompt,
    events_from_tool_use,
    response_indicates_error,
)
from .llm.base import LLMProvider
from .schemas import Event, MemoryBank
from .store import SqliteStore, open_store
from .triggers import TriggerState
from .triggers import default as default_trigger

logger = logging.getLogger("agentmem")

# Called when a trigger fires: (config, session_id, tool_failure) -> None. Real use
# spawns a detached process; tests pass a synchronous runner so a step is deterministic.
StepRunner = Callable[[AgentMemConfig, str, bool], None]

_WINDOW = 16  # recent events kept on disk for the memory-step


@dataclass
class LiveState:
    """The conversation-local state a cold hook needs: what the task is, how far along
    we are, and the recent window. The bank (long-term memory) lives in the store."""

    task: str = ""
    turn: int = 0
    step: int = 0
    turn_at_last_step: int = 0
    events: list[dict[str, object]] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> LiveState:
        try:
            return cls(**json.loads(path.read_text()))
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(self)))
        tmp.replace(path)  # atomic on POSIX

    def window(self) -> list[Event]:
        return [Event.model_validate(e) for e in self.events]

    def add(self, events: list[Event]) -> None:
        self.events.extend(e.model_dump() for e in events)
        self.events = self.events[-_WINDOW:]


def _live_dir(config: AgentMemConfig) -> Path:
    return Path(config.state_dir) / "live"


def _state_path(config: AgentMemConfig, session_id: str) -> Path:
    return _live_dir(config) / f"{session_id}.json"


def _pending_path(config: AgentMemConfig, session_id: str) -> Path:
    return _live_dir(config) / f"{session_id}.pending"


def write_pending(config: AgentMemConfig, session_id: str, text: str) -> None:
    path = _pending_path(config, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def take_pending(config: AgentMemConfig, session_id: str) -> str | None:
    """Read the pending reminder and delete it: reminders are consumed once."""
    path = _pending_path(config, session_id)
    try:
        text = path.read_text()
    except OSError:
        return None
    path.unlink(missing_ok=True)
    return text or None


def _load_banks(config: AgentMemConfig, session_id: str) -> tuple[MemoryBank, MemoryBank | None]:
    store = open_store(config.store, config.state_dir)
    try:
        session_bank = store.load_bank(session_id) or MemoryBank()
    finally:
        store.close()
    project_bank = None
    if config.continual_enabled:
        project_store = SqliteStore(f"{config.state_dir}/project.db")
        try:
            project_bank = project_store.load_bank("project")
        finally:
            project_store.close()
    return session_bank, project_bank


def _spawn_step(config: AgentMemConfig, session_id: str, bypass_cooldown: bool) -> None:
    """Fire-and-forget the memory-step so the hook returns immediately."""
    cmd = [sys.executable, "-m", "agentmem", "_step", session_id, "--state-dir", config.state_dir]
    if bypass_cooldown:
        cmd.append("--tool-failure")
    subprocess.Popen(  # noqa: S603 - args are ours, not user input
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def on_session_start(config: AgentMemConfig, session_id: str) -> str | None:
    """Recap durable memory for a new conversation, and drop the stale event window."""
    session_bank, project_bank = _load_banks(config, session_id)
    path = _state_path(config, session_id)
    state = LiveState.load(path)
    state.events = []  # a new conversation shouldn't reason over the last one's window
    state.turn_at_last_step = state.turn
    state.save(path)
    return bank_digest(session_bank, project=project_bank)


def on_prompt(
    config: AgentMemConfig, session_id: str, prompt: str, *, step_runner: StepRunner | None = None
) -> str | None:
    return _ingest(config, session_id, [event_from_prompt(prompt)], False, prompt, step_runner)


def on_post_tool(
    config: AgentMemConfig,
    session_id: str,
    tool_name: str,
    tool_input: object,
    tool_response: object,
    *,
    step_runner: StepRunner | None = None,
) -> str | None:
    ok = not response_indicates_error(tool_response)
    events = events_from_tool_use(tool_name, tool_input, tool_response, ok=ok)
    return _ingest(config, session_id, events, not ok, None, step_runner)


def _ingest(
    config: AgentMemConfig,
    session_id: str,
    events: list[Event],
    is_failure: bool,
    task: str | None,
    step_runner: StepRunner | None,
) -> str | None:
    path = _state_path(config, session_id)
    state = LiveState.load(path)
    if task and not state.task:
        state.task = task  # the first prompt is the task
    state.turn += 1
    state.add(events)

    trigger = default_trigger(config.trigger_every_n)
    fired = bool(
        trigger(
            TriggerState(
                turn=state.turn,
                batch=events,
                history=state.window(),
                turns_since_step=state.turn - state.turn_at_last_step,
            )
        )
    )
    if fired:
        state.step += 1
        state.turn_at_last_step = state.turn
    state.save(path)

    if fired:
        (step_runner or _spawn_step)(config, session_id, is_failure)
    # Deliver whatever a prior step already computed; this step's reminder lands next hook.
    return take_pending(config, session_id)


def run_step_cold(
    config: AgentMemConfig,
    session_id: str,
    *,
    bypass_cooldown: bool = False,
    provider: LLMProvider | None = None,
) -> None:
    """One memory-step against the on-disk bank, then write any reminder for the next
    hook. This is what `agentmem _step` runs, detached, off the hook's hot path."""
    from .agent.memory_agent import MemoryAgent
    from .redactor import make_redactor

    state = LiveState.load(_state_path(config, session_id))
    session_bank, _ = _load_banks(config, session_id)
    agent = MemoryAgent(
        provider or _provider(config),
        config,
        redactor=make_redactor(config.redact_secrets),
    )
    outcome = agent.run_step(
        state.task,
        state.window(),
        session_bank,
        state.step,
        bypass_cooldown=bypass_cooldown,
        trigger="tool_failure" if bypass_cooldown else "hook",
    )
    store = open_store(config.store, config.state_dir)
    try:
        store.save_bank(session_id, state.task, outcome.bank)
    finally:
        store.close()
    if outcome.result.intervention is not None:
        write_pending(config, session_id, outcome.result.intervention.text)


def on_pre_compact(
    config: AgentMemConfig, session_id: str, *, provider: LLMProvider | None = None
) -> None:
    """Capture the recent window into the bank before the transcript is compacted away.
    PreCompact allows a long timeout, so this runs the step synchronously."""
    run_step_cold(config, session_id, provider=provider)


def on_session_end(config: AgentMemConfig, session_id: str) -> None:
    """Consolidate, promote, and persist at the end of a conversation. Reuses the full
    session machinery synchronously; SessionEnd isn't on any latency-critical path.
    Best-effort: a failure here must not break the hook that called it."""
    from .session import MemorySession

    task = LiveState.load(_state_path(config, session_id)).task
    try:
        # close() runs end_session() once (consolidate, grade, promote), then persists.
        MemorySession(task=task, config=config, session_id=session_id, async_worker=False).close()
    except Exception as exc:
        logger.warning("session-end housekeeping skipped: %s", exc)
    _state_path(config, session_id).unlink(missing_ok=True)
    _pending_path(config, session_id).unlink(missing_ok=True)


def _provider(config: AgentMemConfig) -> LLMProvider:
    from .llm import make_provider

    return make_provider(config)
