"""Golden tests for the advantage estimate — every number is hand-computable."""

from __future__ import annotations

import pytest
from agentmem.policy.advantage import estimate
from agentmem.policy.policy_store import DecisionRecord

SIG = ["a", "b", "c"]


def _rec(action: str, g: float, sig: list[str] | None = None) -> DecisionRecord:
    return DecisionRecord(state_sig=sig if sig is not None else SIG, action=action, g=g)  # type: ignore[arg-type]


def test_basic_advantage() -> None:
    records = [_rec("inject", 0.8), _rec("inject", 0.4), _rec("silent", -0.2), _rec("silent", 0.0)]
    adv = estimate(SIG, records)

    assert adv is not None
    assert adv.n == 4 and adv.n_inject == 2 and adv.n_silent == 2
    assert adv.v == pytest.approx(0.25)
    assert adv.q_inject == pytest.approx(0.6)
    assert adv.q_silent == pytest.approx(-0.1)
    # Raw advantages are +0.35 / -0.35, so normalized they hit +1 / -1.
    assert adv.a_inject == pytest.approx(1.0, abs=1e-6)
    assert adv.a_silent == pytest.approx(-1.0, abs=1e-6)


def test_below_threshold_neighbors_dropped() -> None:
    # The only record barely overlaps the query, so there are no neighbors.
    assert estimate(SIG, [_rec("inject", 1.0, sig=["x", "y", "z"])]) is None


def test_no_records_is_none() -> None:
    assert estimate(SIG, []) is None


def test_optimism_bonus_for_untried_action() -> None:
    records = [_rec("silent", 0.5), _rec("silent", 0.5)]  # inject never tried here
    adv = estimate(SIG, records, alpha=0.3, optimism=True)

    assert adv is not None
    assert adv.n_inject == 0
    assert adv.q_inject == pytest.approx(0.5 + 0.3 / 2)  # v + alpha/n
    assert adv.a_inject > 0  # optimism keeps injecting explorable


def test_optimism_off_zeroes_untried_action() -> None:
    records = [_rec("silent", 0.5), _rec("silent", 0.5)]
    adv = estimate(SIG, records, optimism=False)

    assert adv is not None
    assert adv.q_inject == 0.0
    assert adv.a_inject < 0  # with v=0.5, an untried inject looks worse


def test_topk_caps_neighbors() -> None:
    records = [_rec("inject", 0.5) for _ in range(30)]
    adv = estimate(SIG, records, k=16)
    assert adv is not None
    assert adv.n == 16
