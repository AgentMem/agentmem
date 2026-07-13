"""Daemon endpoint tests, driven through FastAPI's TestClient."""

from __future__ import annotations

import time
from pathlib import Path

from _helpers import CWD, tool_fail_payload
from agentmem import MemorySession
from agentmem.config import AgentMemConfig
from agentmem.integrations.claude_code import project_key
from agentmem.llm.base import LLMResponse
from agentmem.schemas import TokenUsage
from agentmem_daemon import create_app
from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_tool_failure_flow_delivers_reminder(client: TestClient) -> None:
    # First failure: the memory agent records it but stays silent.
    r1 = client.post("/hook/tool-fail", json=tool_fail_payload())
    assert r1.json() == {}

    # Second identical failure: now it speaks, and the reminder rides back on the
    # hook response as additionalContext.
    r2 = client.post("/hook/tool-fail", json=tool_fail_payload())
    ctx = r2.json()["hookSpecificOutput"]["additionalContext"]
    assert "P-001" in ctx
    assert "DEFAULT_TTL" in ctx


def test_post_tool_detects_failure_from_exit_code(client: TestClient) -> None:
    # /hook/post-tool fires on "success", but a non-zero exit is still a failure.
    payload = {
        "cwd": CWD,
        "tool_name": "Bash",
        "tool_input": {"command": "pytest"},
        "tool_response": {"exit_code": 1, "stdout": "FAILED"},
    }
    client.post("/hook/post-tool", json=payload)
    r2 = client.post("/hook/post-tool", json=payload)
    assert "P-001" in r2.json()["hookSpecificOutput"]["additionalContext"]


def test_session_start_recaps_prior_memory(client: TestClient) -> None:
    # Build up some memory...
    client.post("/hook/tool-fail", json=tool_fail_payload())
    client.post("/hook/tool-fail", json=tool_fail_payload())
    # ...then a fresh session-start hands it back (cross-session project memory).
    r = client.post("/hook/session-start", json={"cwd": CWD})
    ctx = r.json()["hookSpecificOutput"]["additionalContext"]
    assert "Memory from earlier sessions" in ctx
    assert "K-001" in ctx or "P-001" in ctx


def test_session_start_empty_project_is_silent(client: TestClient) -> None:
    r = client.post("/hook/session-start", json={"cwd": CWD})
    assert r.json() == {}  # nothing learned yet, nothing to say


def test_prompt_sets_task_and_returns_pending(client: TestClient) -> None:
    r = client.post("/hook/prompt", json={"cwd": CWD, "prompt": "fix the failing auth tests"})
    assert r.json() == {}  # nothing pending on the very first prompt

    mem = client.app.state.registry.get(project_key(CWD))
    assert mem is not None
    assert mem.task == "fix the failing auth tests"  # placeholder was upgraded


def test_pre_compact_forces_a_step(client: TestClient) -> None:
    client.post("/hook/tool-fail", json=tool_fail_payload())  # step 1
    r = client.post("/hook/pre-compact", json={"cwd": CWD})
    assert r.json() == {}
    mem = client.app.state.registry.get(project_key(CWD))
    assert mem is not None
    assert mem.bank.version >= 1  # consolidation ran


def test_session_end_is_clean(client: TestClient) -> None:
    client.post("/hook/tool-fail", json=tool_fail_payload())
    r = client.post("/hook/session-end", json={"cwd": CWD})
    assert r.status_code == 200
    assert r.json() == {}


def test_session_end_consolidates_without_closing_the_session(client: TestClient) -> None:
    client.post("/hook/tool-fail", json=tool_fail_payload())  # step 1: silent
    client.post("/hook/session-end", json={"cwd": CWD})

    mem = client.app.state.registry.get(project_key(CWD))
    assert mem is not None
    assert mem.bank.sessions_seen == 1  # end_session() ran, not close()

    # The registry's long-lived session must still be usable for the *next* Claude
    # Code session on this project: the scripted provider's second step speaks up.
    r = client.post("/hook/tool-fail", json=tool_fail_payload())
    assert "P-001" in r.json()["hookSpecificOutput"]["additionalContext"]


def test_malformed_body_does_not_crash(client: TestClient) -> None:
    # A hook must never 500 over a weird payload; worst case it does nothing.
    r = client.post(
        "/hook/post-tool", content="not json at all", headers={"content-type": "application/json"}
    )
    assert r.status_code == 200
    assert r.json() == {}


class _SlowProvider:
    """Takes half a second per call, so we can prove the hook doesn't wait on it."""

    model = "slow"

    def complete(self, **_: object) -> LLMResponse:
        time.sleep(0.5)
        return LLMResponse(text="<no_intervention/>", usage=TokenUsage(model="slow"))


def test_hook_returns_before_the_memory_step_finishes(tmp_path: Path) -> None:
    # The whole point of the background worker: a slow memory-step must not slow the
    # hook. observe() enqueues and returns; the 0.5s step runs behind it.
    def factory(key: str, cwd: str, task: str) -> MemorySession:
        config = AgentMemConfig(state_dir=str(tmp_path / key), max_tool_rounds=1)
        return MemorySession(
            task=task, session_id=key, config=config, provider=_SlowProvider(), async_worker=True
        )

    with TestClient(create_app(factory=factory)) as c:
        start = time.perf_counter()
        r = c.post("/hook/tool-fail", json=tool_fail_payload())
        elapsed = time.perf_counter() - start

    assert r.status_code == 200
    assert elapsed < 0.3, f"hook blocked on the LLM step ({elapsed:.2f}s)"
