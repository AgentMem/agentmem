"""The daemon-less command-hook runtime: state lives on disk between invocations,
the reminder a step computes is delivered by a later hook."""

from __future__ import annotations

from pathlib import Path

import pytest
from _fakes import FakeProvider, text_response, tool_response
from agentmem import hookrunner
from agentmem.config import AgentMemConfig
from agentmem.hookrunner import LiveState, _pending_path, _state_path
from agentmem.schemas import Event, MemoryBank, MemoryEntry
from agentmem.store import open_store
from agentmem.tools import SAVE_KNOWLEDGE, ToolCall

_INJECT = "<context_for_action>\n- (K-001) keep the public API stable\n</context_for_action>"


def _cfg(tmp_path: Path) -> AgentMemConfig:
    return AgentMemConfig(state_dir=str(tmp_path), max_tool_rounds=1)


def _reminding_provider() -> FakeProvider:
    return FakeProvider(
        phase1=[
            tool_response(
                ToolCall(
                    name=SAVE_KNOWLEDGE,
                    args={"tag": "task", "content": "keep the public API stable"},
                    block_id="k",
                )
            )
        ],
        phase2=[text_response(_INJECT)],
    )


def _sync_runner(provider: FakeProvider) -> hookrunner.StepRunner:
    def run(config: AgentMemConfig, session_id: str, bypass: bool) -> None:
        hookrunner.run_step_cold(config, session_id, bypass_cooldown=bypass, provider=provider)

    return run


def test_session_start_is_silent_when_there_is_no_memory(tmp_path: Path) -> None:
    assert hookrunner.on_session_start(_cfg(tmp_path), "s1") is None


def test_session_start_recaps_a_seeded_bank(tmp_path: Path) -> None:
    store = open_store("json", str(tmp_path))
    store.save_bank(
        "s1",
        "fix",
        MemoryBank(
            knowledge={
                "K-001": MemoryEntry(
                    id="K-001",
                    kind="knowledge",
                    tag="task",
                    content="keep the public API stable",
                    created_step=1,
                    updated_step=1,
                )
            }
        ),
    )
    store.close()

    digest = hookrunner.on_session_start(_cfg(tmp_path), "s1")
    assert digest is not None
    assert "K-001" in digest


def test_a_step_writes_a_reminder_that_a_later_hook_delivers_once(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    # Seed the live window + task, as prior hooks would have.
    state = LiveState(
        task="fix the tests",
        step=1,
        events=[Event(kind="tool_result", tool_name="bash", ok=False, text="FAILED").model_dump()],
    )
    state.save(_state_path(cfg, "s1"))

    hookrunner.run_step_cold(cfg, "s1", provider=_reminding_provider())  # writes the pending file

    quiet: hookrunner.StepRunner = lambda *_: None  # noqa: E731
    delivered = hookrunner.on_prompt(cfg, "s1", "what next?", step_runner=quiet)
    assert delivered is not None and "K-001" in delivered
    # Consumed once: a second hook sees nothing.
    assert hookrunner.on_prompt(cfg, "s1", "and now?", step_runner=quiet) is None


def test_post_tool_fires_the_first_step_and_persists_the_bank(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    hookrunner.on_post_tool(
        cfg,
        "s1",
        "bash",
        {"command": "pytest"},
        {"stdout": "FAILED test_x"},
        step_runner=_sync_runner(_reminding_provider()),
    )
    bank = open_store("json", str(tmp_path)).load_bank("s1")
    assert bank is not None and "K-001" in bank.knowledge  # the step ran and saved


def test_first_prompt_becomes_the_task(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    quiet: hookrunner.StepRunner = lambda *_: None  # noqa: E731
    hookrunner.on_prompt(cfg, "s1", "fix the failing auth tests", step_runner=quiet)
    assert LiveState.load(_state_path(cfg, "s1")).task == "fix the failing auth tests"


def test_session_end_runs_housekeeping_and_clears_live_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")  # empty bank => no real call
    cfg = _cfg(tmp_path)
    LiveState(task="fix", step=2).save(_state_path(cfg, "s1"))
    hookrunner.write_pending(cfg, "s1", "stale reminder")

    hookrunner.on_session_end(cfg, "s1")

    assert not _state_path(cfg, "s1").exists()
    assert not _pending_path(cfg, "s1").exists()
    reloaded = open_store("json", str(tmp_path)).load_bank("s1")
    assert reloaded is not None and reloaded.sessions_seen == 1
