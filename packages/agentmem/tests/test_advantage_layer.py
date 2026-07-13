"""Tests for the AdvantageLayer: prior text, the one-way gate, and record/finalize."""

from __future__ import annotations

from pathlib import Path

from _fakes import FakeProvider, text_response
from agentmem.config import AgentMemConfig
from agentmem.policy.advantage import Advantage
from agentmem.policy.evaluator import StepSummary
from agentmem.policy.layer import AdvantageLayer
from agentmem.policy.policy_store import PolicyStore


def _adv(a_inject: float, n: int = 5) -> Advantage:
    return Advantage(
        v=0.2,
        q_silent=0.4,
        q_inject=-0.1,
        a_silent=1.0,
        a_inject=a_inject,
        n=n,
        n_silent=3,
        n_inject=2,
    )


def test_prior_block_reports_the_numbers(tmp_path: Path) -> None:
    layer = AdvantageLayer(PolicyStore(tmp_path / "p.db"), AgentMemConfig())
    block = layer.prior_block(_adv(a_inject=-1.0))
    assert block is not None
    assert "injecting averaged" in block
    assert "n=2" in block and "n=3" in block


def test_gate_off_by_default(tmp_path: Path) -> None:
    layer = AdvantageLayer(PolicyStore(tmp_path / "p.db"), AgentMemConfig())  # gate default off
    assert layer.should_gate(_adv(a_inject=-1.0)) is False


def test_gate_forces_silence_when_inject_looks_bad(tmp_path: Path) -> None:
    layer = AdvantageLayer(PolicyStore(tmp_path / "p.db"), AgentMemConfig(advantage_gate=True))
    assert layer.should_gate(_adv(a_inject=-0.5, n=5)) is True  # enough evidence, inject worse
    assert layer.should_gate(_adv(a_inject=0.5, n=5)) is False  # inject looks fine
    assert layer.should_gate(_adv(a_inject=-0.5, n=2)) is False  # too few neighbors
    assert layer.should_gate(None) is False  # nothing to go on


def test_retrieve_uses_finalized_history(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path / "p.db")
    for i in range(4):
        store.record(
            session_id="old",
            step=i,
            state_sig=["trigger:tool_failure", "fails:1"],
            action="inject",
            inject_class=None,
            model="m",
        )
    store.finalize("old", dict.fromkeys(range(4), 0.6))

    layer = AdvantageLayer(store, AgentMemConfig())  # snapshots the finalized rows
    adv = layer.retrieve(["trigger:tool_failure", "fails:1"])
    assert adv is not None
    assert adv.n == 4


def test_record_then_finalize_writes_returns(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path / "p.db")
    layer = AdvantageLayer(store, AgentMemConfig())
    layer.record(session_id="s", step=1, sig=["x"], action="inject", model="haiku")

    provider = FakeProvider(
        phase2=[text_response('[{"step": 1, "reward": 0.8, "label": "prevented_repeat"}]')]
    )
    layer.finalize(
        provider,
        session_id="s",
        task="fix",
        trajectory="...",
        summaries=[StepSummary(step=1, edits="created K-001", decision="reminder")],
        task_reward=1.0,
    )

    finalized = store.finalized()
    assert len(finalized) == 1
    assert finalized[0].g == 1.8  # 0.8 + gamma^0 * 1.0 task reward, single step
    store.close()
