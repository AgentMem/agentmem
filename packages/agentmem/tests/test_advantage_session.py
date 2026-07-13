"""End-to-end advantage layer: a session records and grades its decisions, and the
gate turns a would-be reminder into silence when history says injecting here backfires.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _fakes import FakeProvider, text_response, tool_response
from agentmem import MemorySession
from agentmem.agent.memory_agent import MemoryAgent
from agentmem.bank import apply_tool_calls
from agentmem.config import AgentMemConfig
from agentmem.policy.layer import AdvantageLayer
from agentmem.policy.policy_store import PolicyStore
from agentmem.policy.state_sig import DecisionContext, state_signature
from agentmem.schemas import Event, MemoryBank
from agentmem.tools import SAVE_KNOWLEDGE, SAVE_PROCEDURAL, ToolCall

_FAIL = [Event(kind="tool_result", tool_name="bash", ok=False, text="FAILED test")]
_INJECT = "<context_for_action>\n- (K-001) keep the public API stable\n</context_for_action>"


def test_advantage_off_writes_no_policy_db(tmp_path: Path) -> None:
    provider = FakeProvider(
        phase1=[
            tool_response(
                ToolCall(name=SAVE_KNOWLEDGE, block_id="k", args={"tag": "task", "content": "x"})
            )
        ],
        phase2=[text_response("<no_intervention/>")],
    )
    config = AgentMemConfig(state_dir=str(tmp_path), max_tool_rounds=1)  # advantage off (default)
    with MemorySession(
        task="t", config=config, provider=provider, session_id="s", async_worker=False
    ) as mem:
        mem.observe(_FAIL)

    assert not (tmp_path / "policy.db").exists()


def test_session_records_and_grades_at_close(tmp_path: Path) -> None:
    provider = FakeProvider(
        phase1=[
            tool_response(
                ToolCall(name=SAVE_KNOWLEDGE, block_id="k", args={"tag": "task", "content": "x"})
            ),
            tool_response(
                ToolCall(
                    name=SAVE_PROCEDURAL, block_id="p", args={"tag": "diagnosis", "content": "y"}
                )
            ),
        ],
        phase2=[
            text_response("<no_intervention/>"),
            text_response("<context_for_action>\n- (K-001) x\n</context_for_action>"),
            # The third phase-2-shaped call is the Outcome Evaluator at SessionEnd.
            text_response('[{"step": 1, "reward": 0.2}, {"step": 2, "reward": 0.8}]'),
        ],
    )
    config = AgentMemConfig(state_dir=str(tmp_path), max_tool_rounds=1, advantage_enabled=True)
    mem = MemorySession(
        task="fix the tests", config=config, provider=provider, session_id="s", async_worker=False
    )
    mem.observe(_FAIL)  # step 1
    mem.observe(_FAIL)  # step 2
    mem.close(task_reward=1.0)

    store = PolicyStore(tmp_path / "policy.db")
    try:
        graded = store.finalized()
        assert len(graded) == 2  # both steps recorded and given a return
        assert sorted(r.g for r in graded) == pytest.approx([1.8, 1.82])
    finally:
        store.close()


def _bank_with_k001() -> MemoryBank:
    return apply_tool_calls(
        MemoryBank(),
        [
            ToolCall(
                name=SAVE_KNOWLEDGE, args={"tag": "task", "content": "keep the public API stable"}
            )
        ],
        step=1,
    ).bank


def _seed_store_where_inject_backfires(path: Path, sig: list[str]) -> PolicyStore:
    store = PolicyStore(path)
    for i in range(5):
        store.record(
            session_id="hist", step=i, state_sig=sig, action="inject", inject_class=None, model="m"
        )
        store.record(
            session_id="hist",
            step=100 + i,
            state_sig=sig,
            action="silent",
            inject_class=None,
            model="m",
        )
    store.finalize("hist", {**dict.fromkeys(range(5), -0.5), **dict.fromkeys(range(100, 105), 0.2)})
    return store


def _run_once(config: AgentMemConfig, store: PolicyStore) -> str:
    provider = FakeProvider(phase1=[tool_response()], phase2=[text_response(_INJECT)])
    agent = MemoryAgent(provider, config, advantage=AdvantageLayer(store, config))
    outcome = agent.run_step(
        "fix the tests",
        _FAIL,
        _bank_with_k001(),
        step=5,
        trigger="tool_failure",
        steps_since_inject=1,
    )
    return outcome.result.decision


def test_gate_flips_inject_to_silent(tmp_path: Path) -> None:
    sig = state_signature(
        DecisionContext(
            trigger="tool_failure",
            window=_FAIL,
            bank=_bank_with_k001(),
            steps_since_inject=1,
            task="fix the tests",
        )
    )
    store = _seed_store_where_inject_backfires(tmp_path / "policy.db", sig)
    try:
        gate_on = AgentMemConfig(
            state_dir=str(tmp_path), max_tool_rounds=1, advantage_enabled=True, advantage_gate=True
        )
        gate_off = AgentMemConfig(
            state_dir=str(tmp_path), max_tool_rounds=1, advantage_enabled=True, advantage_gate=False
        )

        # Same history, same reminder from Phase 2: only the gate differs.
        assert _run_once(gate_off, store) == "inject"
        assert _run_once(gate_on, store) == "silent"
    finally:
        store.close()
