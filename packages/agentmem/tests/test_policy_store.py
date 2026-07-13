"""Tests for the decision store: pending vs finalized, and round-trip."""

from __future__ import annotations

from pathlib import Path

from agentmem.policy.policy_store import PolicyStore


def test_pending_then_finalized(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path / "policy.db")
    try:
        store.record(
            session_id="s",
            step=1,
            state_sig=["trigger:tool_failure", "fails:1"],
            action="inject",
            inject_class="requirement",
            model="haiku",
        )
        # A decision the session hasn't graded yet doesn't count.
        assert store.finalized() == []
        assert store.count() == 0

        store.finalize("s", {1: 0.5})
        records = store.finalized()
        assert len(records) == 1
        assert records[0].g == 0.5
        assert records[0].action == "inject"
        assert records[0].state_sig == ["trigger:tool_failure", "fails:1"]
        assert store.count() == 1
    finally:
        store.close()


def test_finalize_only_touches_its_session(tmp_path: Path) -> None:
    store = PolicyStore(tmp_path / "policy.db")
    try:
        store.record(
            session_id="a", step=1, state_sig=["x"], action="silent", inject_class=None, model="m"
        )
        store.record(
            session_id="b", step=1, state_sig=["y"], action="inject", inject_class="env", model="m"
        )
        store.finalize("a", {1: -0.2})

        finalized = store.finalized()
        assert len(finalized) == 1
        assert finalized[0].session_id == "a"
    finally:
        store.close()


def test_survives_reopen(tmp_path: Path) -> None:
    path = tmp_path / "policy.db"
    store = PolicyStore(path)
    store.record(
        session_id="s", step=1, state_sig=["x"], action="inject", inject_class=None, model="m"
    )
    store.finalize("s", {1: 1.0})
    store.close()

    reopened = PolicyStore(path)
    try:
        assert reopened.count() == 1
    finally:
        reopened.close()
