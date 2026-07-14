"""The AUC math on synthetic decision histories."""

from __future__ import annotations

import importlib.util
import random
import sys
from pathlib import Path

from agentmem.policy.policy_store import DecisionRecord

_spec = importlib.util.spec_from_file_location(
    "policy_auc", Path(__file__).resolve().parents[1] / "longrun_sim" / "policy_auc.py"
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["policy_auc"] = _mod
_spec.loader.exec_module(_mod)


def _rec(sig: list[str], action: str, g: float, i: int) -> DecisionRecord:
    return DecisionRecord(state_sig=sig, action=action, g=g, session_id="s", step=i)


def test_auc_ranks_a_predictive_history_high() -> None:
    # In "fail" states injecting pays; in "calm" states it costs. The estimator
    # should rank taken-action advantages consistently with realized g.
    records = []
    i = 0
    for _ in range(30):
        records.append(_rec(["fail", "repeat", "tool:pytest"], "inject", 0.8, i))
        i += 1
        records.append(_rec(["fail", "repeat", "tool:pytest"], "silent", -0.5, i))
        i += 1
        records.append(_rec(["calm", "fresh", "tool:ls"], "silent", 0.6, i))
        i += 1
        records.append(_rec(["calm", "fresh", "tool:ls"], "inject", -0.4, i))
        i += 1
    pairs = _mod.loo_scores(records)
    assert len(pairs) == len(records)
    a = _mod.auc(pairs, 0.0)
    assert a is not None and a > 0.8


def test_auc_is_chance_on_shuffled_outcomes() -> None:
    rng = random.Random(11)
    gs = [0.7, -0.7] * 30
    rng.shuffle(gs)
    records = []
    for i, g in enumerate(gs):
        sig = [rng.choice(["fail", "calm", "flaky"]), f"tok{rng.randrange(5)}"]
        records.append(_rec(sig, rng.choice(["inject", "silent"]), g, i))
    pairs = _mod.loo_scores(records)
    a = _mod.auc(pairs, 0.0)
    assert a is not None and 0.3 < a < 0.7


def test_auc_undefined_when_one_sided() -> None:
    pairs = [(0.5, 1.0), (0.2, 0.9)]
    assert _mod.auc(pairs, 0.0) is None
