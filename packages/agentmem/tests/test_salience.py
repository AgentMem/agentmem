"""Golden tests for the salience score and lifecycle classification — every number
here is hand-computable from the weights in salience.py."""

from __future__ import annotations

import pytest
from agentmem.salience import (
    ACTIVE_MIN,
    DORMANT_MIN,
    FLOOR_SALIENCE,
    SalienceWeights,
    classify,
    compute_salience,
    recompute_lifecycle,
)
from agentmem.schemas import EntryLifecycle, MemoryBank, MemoryEntry

W = SalienceWeights()  # recency=.25 frequency=.15 importance=.35 reinforcement=.25


def _entry(**overrides: object) -> MemoryEntry:
    defaults: dict[str, object] = {
        "id": "K-001",
        "kind": "knowledge",
        "tag": "other",
        "content": "x",
        "created_step": 1,
        "updated_step": 1,
    }
    defaults.update(overrides)
    return MemoryEntry(**defaults)  # type: ignore[arg-type]


def test_fresh_entry_touched_this_session() -> None:
    # delta_sessions=0 -> recency=1.0; untouched -> frequency=0; tag "other" -> I=0.3.
    e = _entry(lifecycle=EntryLifecycle(last_touched_session=10))
    s = compute_salience(e, sessions_seen=10, max_access_count=5, weights=W)
    assert s == pytest.approx(0.25 * 1.0 + 0.35 * 0.3)  # 0.355
    assert classify(s) == "dormant"  # between DORMANT_MIN and ACTIVE_MIN


def test_recency_half_life_is_five_sessions() -> None:
    e = _entry(lifecycle=EntryLifecycle(last_touched_session=0))
    s = compute_salience(e, sessions_seen=5, max_access_count=0, weights=W)
    assert s == pytest.approx(0.25 * 0.5 + 0.35 * 0.3)  # recency halved


def test_frequency_term_is_log_ratio_against_the_busiest_entry() -> None:
    e = _entry(access_count=7, lifecycle=EntryLifecycle(last_touched_session=10))
    s = compute_salience(e, sessions_seen=10, max_access_count=7, weights=W)
    # recency=1 (just touched), frequency=log1p(7)/log1p(7)=1, importance=0.3
    assert s == pytest.approx(0.25 * 1.0 + 0.15 * 1.0 + 0.35 * 0.3)
    assert classify(s) == "active"  # crosses ACTIVE_MIN at 0.505


def test_reinforcement_can_push_below_zero_but_clamps() -> None:
    e = _entry(lifecycle=EntryLifecycle(last_touched_session=0, reinforcement=-1.0))
    s = compute_salience(e, sessions_seen=1000, max_access_count=0, weights=W)
    assert s == 0.0  # clamped; the raw score is negative
    assert classify(s) == "archived"


def test_policy_tag_is_floored_at_active_even_with_zero_everything_else() -> None:
    e = _entry(tag="policy", lifecycle=EntryLifecycle(last_touched_session=0))
    s = compute_salience(e, sessions_seen=1000, max_access_count=0, weights=W)
    assert s == FLOOR_SALIENCE
    assert classify(s) == "active"


def test_task_tag_gets_the_same_floor() -> None:
    e = _entry(tag="task", lifecycle=EntryLifecycle(last_touched_session=0, reinforcement=-1.0))
    s = compute_salience(e, sessions_seen=1000, max_access_count=0, weights=W)
    assert s == FLOOR_SALIENCE


def test_classify_boundaries() -> None:
    assert classify(ACTIVE_MIN) == "active"
    assert classify(ACTIVE_MIN - 0.001) == "dormant"
    assert classify(DORMANT_MIN) == "dormant"
    assert classify(DORMANT_MIN - 0.001) == "archived"


def test_weights_from_config_duck_types() -> None:
    class Cfg:
        continual_w_recency = 0.1
        continual_w_frequency = 0.2
        continual_w_importance = 0.3
        continual_w_reinforcement = 0.4

    w = SalienceWeights.from_config(Cfg())
    assert (w.recency, w.frequency, w.importance, w.reinforcement) == (0.1, 0.2, 0.3, 0.4)


def test_weights_from_config_falls_back_on_missing_attrs() -> None:
    assert SalienceWeights.from_config(object()) == SalienceWeights()


def test_recompute_lifecycle_moves_archived_entries_out_of_the_live_dict() -> None:
    bank = MemoryBank(
        sessions_seen=1000,
        knowledge={
            "K-001": _entry(
                id="K-001", lifecycle=EntryLifecycle(last_touched_session=0, reinforcement=-1.0)
            ),
            "K-002": _entry(
                id="K-002", tag="policy", lifecycle=EntryLifecycle(last_touched_session=0)
            ),
        },
    )
    out = recompute_lifecycle(bank)

    assert "K-001" not in out.knowledge
    assert out.archive["K-001"].lifecycle.state == "archived"
    assert out.knowledge["K-002"].lifecycle.state == "active"  # floor-protected, stays put


def test_recompute_lifecycle_is_pure() -> None:
    bank = MemoryBank(
        sessions_seen=1000,
        knowledge={
            "K-001": _entry(lifecycle=EntryLifecycle(last_touched_session=0, reinforcement=-1.0))
        },
    )
    recompute_lifecycle(bank)
    assert "K-001" in bank.knowledge  # the original is untouched
    assert bank.archive == {}


def test_recompute_lifecycle_uses_the_busiest_entry_in_the_bank_as_the_frequency_ceiling() -> None:
    bank = MemoryBank(
        sessions_seen=0,
        knowledge={
            "K-001": _entry(id="K-001", access_count=10, lifecycle=EntryLifecycle()),
            "K-002": _entry(id="K-002", access_count=0, lifecycle=EntryLifecycle()),
        },
    )
    out = recompute_lifecycle(bank)
    # K-001 is the busiest entry in its own bank, so its frequency term hits 1.0.
    assert out.knowledge["K-001"].lifecycle.salience > out.knowledge["K-002"].lifecycle.salience
