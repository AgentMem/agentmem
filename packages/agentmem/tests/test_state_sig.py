"""Tests for state signatures: similar situations should overlap, different ones not."""

from __future__ import annotations

from agentmem.policy.state_sig import DecisionContext, jaccard, state_signature
from agentmem.schemas import Event, MemoryBank, MemoryEntry


def _fail_window(cmd: str = "pytest -q") -> list[Event]:
    return [
        Event(kind="tool_call", tool_name="bash", text=cmd),
        Event(kind="tool_result", tool_name="bash", ok=False, text="FAILED test"),
    ]


def test_signature_tokens() -> None:
    ctx = DecisionContext(
        trigger="tool_failure",
        window=_fail_window(),
        bank=MemoryBank(),
        steps_since_inject=1,
        task="fix the auth tests",
    )
    sig = state_signature(ctx)
    assert "trigger:tool_failure" in sig
    assert "tool:bash:fail" in sig
    assert "fails:1" in sig
    assert "since_inject:0-2" in sig
    assert "bankK:0" in sig
    assert "task:auth" in sig


def test_similar_states_overlap() -> None:
    a = state_signature(
        DecisionContext(
            trigger="tool_failure",
            window=_fail_window("pytest -k test_a"),
            steps_since_inject=1,
            task="fix auth",
        )
    )
    b = state_signature(
        DecisionContext(
            trigger="tool_failure",
            window=_fail_window("pytest -k test_b"),
            steps_since_inject=2,
            task="fix auth",
        )
    )
    assert jaccard(a, b) > 0.7  # only the test name and one bucket differ


def test_similar_beats_different() -> None:
    base = state_signature(
        DecisionContext(
            trigger="tool_failure",
            window=_fail_window("pytest -k test_a"),
            steps_since_inject=1,
            task="fix the auth tests",
        )
    )
    similar = state_signature(
        DecisionContext(
            trigger="tool_failure",
            window=_fail_window("pytest -k test_b"),
            steps_since_inject=2,
            task="fix the auth tests",
        )
    )
    different = state_signature(
        DecisionContext(
            trigger="interval",
            window=[Event(kind="message", role="assistant", text="planning")],
            steps_since_inject=8,
            task="build a yaml parser",
        )
    )
    assert jaccard(base, similar) > jaccard(base, different) + 0.3


def test_command_variants_collapse() -> None:
    a = state_signature(DecisionContext(window=_fail_window("pytest -k test_alpha")))
    b = state_signature(DecisionContext(window=_fail_window("pytest -k test_beta_2")))
    assert [t for t in a if t.startswith("cmd:")] == [t for t in b if t.startswith("cmd:")]


def test_bank_size_buckets() -> None:
    bank = MemoryBank()
    for i in range(8):
        bank.knowledge[f"K-{i:03d}"] = MemoryEntry(
            id=f"K-{i:03d}", kind="knowledge", content="x", created_step=1, updated_step=1
        )
    sig = state_signature(DecisionContext(bank=bank))
    assert "bankK:6-15" in sig
