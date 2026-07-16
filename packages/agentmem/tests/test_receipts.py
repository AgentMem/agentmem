"""The receipts summary, and the hook runtime actually feeding it."""

from __future__ import annotations

from pathlib import Path

from _fakes import FakeProvider, text_response, tool_response
from agentmem import hookrunner
from agentmem.config import AgentMemConfig
from agentmem.receipts import render, summarize
from agentmem.telemetry import read_events
from agentmem.tools import SAVE_KNOWLEDGE, ToolCall

INJECT = "<context_for_action>\n- (K-001) mind the TTL\n</context_for_action>"


def _entry(session: str, decision: str, step: int, text: str | None = None) -> dict:
    return {
        "session_id": session,
        "step": step,
        "decision": decision,
        "intervention_text": text,
        "cited_ids": ["K-001"] if text else [],
        "tool_calls": [{"created": "K-001"}] if step == 1 else [],
    }


def test_summarize_counts_per_session_and_total() -> None:
    s = summarize(
        [
            _entry("a", "silent", 1),
            _entry("a", "inject", 2, "- (K-001) mind the TTL"),
            _entry("b", "silent", 1),
        ]
    )
    assert s["steps"] == 3 and s["injects"] == 1 and s["edits"] == 2
    assert s["sessions"]["a"]["injects"] == 1
    assert s["sessions"]["b"]["reminders"] == []


def test_render_says_silence_is_the_default_when_nothing_fired() -> None:
    out = render(summarize([_entry("a", "silent", 1)]))
    assert "silence" in out


def test_render_shows_the_reminder_with_its_citations() -> None:
    out = render(summarize([_entry("a", "inject", 2, "- (K-001) mind the TTL")]))
    assert "K-001" in out and "mind the TTL" in out


def test_the_hook_path_writes_telemetry_receipts_can_read(tmp_path: Path) -> None:
    """Before this, a plugin user had no record of what fired; replay and receipts
    only worked for MemorySession runs."""
    cfg = AgentMemConfig(state_dir=str(tmp_path), max_tool_rounds=1)
    provider = FakeProvider(
        phase1=[
            tool_response(
                ToolCall(name=SAVE_KNOWLEDGE, args={"tag": "task", "content": "x"}, block_id="k")
            )
        ],
        phase2=[text_response(INJECT)],
    )
    hookrunner.on_post_tool(
        cfg,
        "s1",
        "bash",
        {"command": "pytest"},
        {"stdout": "FAILED"},
        step_runner=lambda c, s, b: hookrunner.run_step_cold(
            c, s, bypass_cooldown=b, provider=provider
        ),
    )

    events = read_events(tmp_path / "telemetry.jsonl")
    assert events, "run_step_cold wrote no telemetry"
    s = summarize(events)
    assert s["steps"] == 1 and s["injects"] == 1
    assert "K-001" in render(s)
