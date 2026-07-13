"""Estimate whether injecting or staying silent tends to pay off in a state like this
one, from the graded history.

The recipe is JitRL's, without any gradient step: pull the nearest past decisions by
signature overlap, average their returns to get a baseline V, average within each
action to get Q, and the advantage is Q - V. An action we've never tried here gets an
optimism bonus so the layer doesn't quietly rule out exploring it.

With too few neighbors it returns None, and the caller falls back to plain Phase 2,
a thin slice of history should never override the model.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean

from .policy_store import DecisionRecord
from .state_sig import jaccard

_EPS = 1e-9


@dataclass
class Advantage:
    v: float  # baseline value of the state
    q_silent: float
    q_inject: float
    a_silent: float  # normalized advantage of staying silent
    a_inject: float  # normalized advantage of injecting
    n: int  # neighbors found
    n_silent: int
    n_inject: int


def estimate(
    sig: list[str],
    records: list[DecisionRecord],
    *,
    k: int = 16,
    threshold: float = 0.35,
    alpha: float = 0.3,
    optimism: bool = True,
) -> Advantage | None:
    scored = [(jaccard(sig, r.state_sig), r) for r in records]
    neighbors = [
        r for score, r in sorted(scored, key=lambda x: x[0], reverse=True) if score >= threshold
    ][:k]
    if not neighbors:
        return None

    v = fmean(r.g for r in neighbors)
    inject = [r.g for r in neighbors if r.action == "inject"]
    silent = [r.g for r in neighbors if r.action == "silent"]

    q_inject = _action_value(inject, v, len(neighbors), alpha, optimism)
    q_silent = _action_value(silent, v, len(neighbors), alpha, optimism)

    a_inject_raw = q_inject - v
    a_silent_raw = q_silent - v
    norm = max(abs(a_inject_raw), abs(a_silent_raw)) + _EPS
    return Advantage(
        v=v,
        q_silent=q_silent,
        q_inject=q_inject,
        a_silent=a_silent_raw / norm,
        a_inject=a_inject_raw / norm,
        n=len(neighbors),
        n_silent=len(silent),
        n_inject=len(inject),
    )


def _action_value(returns: list[float], v: float, n: int, alpha: float, optimism: bool) -> float:
    if returns:
        return fmean(returns)
    # No data for this action here. Optimism-under-uncertainty keeps an untried action
    # from being pre-emptively suppressed; the bonus shrinks as evidence accumulates.
    return v + alpha / n if optimism else 0.0
