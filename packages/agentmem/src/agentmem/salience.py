"""Score how worth keeping each entry still is, and classify it into the
active -> dormant -> archived lifecycle.

Four signals blend into one score per entry: how recently it was touched, how
often it gets used, how much its tag matters on its own, and whether the
evaluator's reinforcement signal says it actually helped. Nothing here deletes:
low salience only demotes an entry, and `policy`/`task` entries have a floor that
keeps them in `active` through decay alone.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .schemas import EntryTag, LifecycleState, MemoryBank, MemoryEntry

# I(e): how much a tag matters on its own, independent of usage history.
TAG_IMPORTANCE: dict[EntryTag, float] = {
    "policy": 1.0,
    "task": 1.0,
    "env": 0.7,
    "path": 0.7,
    "diagnosis": 0.6,
    "fix": 0.6,
    "bug": 0.5,
    "perf": 0.5,
    "attempt": 0.3,
    "other": 0.3,
}

# These tags never decay out of `active` on salience alone (only `supersedes` or an
# explicit delete removes them).
FLOOR_TAGS: frozenset[str] = frozenset({"policy", "task"})
FLOOR_SALIENCE = 0.5

ACTIVE_MIN = 0.5
DORMANT_MIN = 0.2

_HALF_LIFE_SESSIONS = 5.0
_DECAY_LAMBDA = math.log(2) / _HALF_LIFE_SESSIONS


@dataclass(frozen=True)
class SalienceWeights:
    recency: float = 0.25
    frequency: float = 0.15
    importance: float = 0.35
    reinforcement: float = 0.25

    @classmethod
    def from_config(cls, config: object) -> SalienceWeights:
        # Duck-typed, same pattern as BankLimits.from_config.
        return cls(
            recency=getattr(config, "continual_w_recency", cls.recency),
            frequency=getattr(config, "continual_w_frequency", cls.frequency),
            importance=getattr(config, "continual_w_importance", cls.importance),
            reinforcement=getattr(config, "continual_w_reinforcement", cls.reinforcement),
        )


def compute_salience(
    entry: MemoryEntry,
    sessions_seen: int,
    max_access_count: int,
    weights: SalienceWeights | None = None,
    *,
    load_bearing: bool = False,
) -> float:
    """S(e): time decay + usage frequency + tag importance + reinforcement, clamped
    to [0, 1]. `policy`/`task` entries are floored at ACTIVE_MIN so decay alone can
    never push them into `dormant`; `load_bearing` (an endpoint of a causal edge)
    grants the same floor, since the graph vouches for the entry."""
    weights = weights or SalienceWeights()
    lc = entry.lifecycle

    delta_sessions = max(0, sessions_seen - lc.last_touched_session)
    recency = math.exp(-_DECAY_LAMBDA * delta_sessions)
    frequency = (
        math.log1p(entry.access_count) / math.log1p(max_access_count)
        if max_access_count > 0
        else 0.0
    )
    importance = TAG_IMPORTANCE.get(entry.tag, 0.3)

    score = (
        weights.recency * recency
        + weights.frequency * frequency
        + weights.importance * importance
        + weights.reinforcement * lc.reinforcement
    )
    if load_bearing or entry.tag in FLOOR_TAGS:
        score = max(score, FLOOR_SALIENCE)
    return max(0.0, min(1.0, score))


def classify(salience: float) -> LifecycleState:
    if salience >= ACTIVE_MIN:
        return "active"
    if salience >= DORMANT_MIN:
        return "dormant"
    return "archived"


def recompute_lifecycle(bank: MemoryBank, weights: SalienceWeights | None = None) -> MemoryBank:
    """Rescore and reclassify every live entry. Pure: returns a new bank.

    Run this once per session, not per step (the per-step capacity check just reads
    whatever salience an entry already has). An entry that lands on `archived` moves
    out of `knowledge`/`procedural` into `bank.archive`; that's the only transition
    that changes which dict an entry lives in.
    """
    new = bank.model_copy(deep=True)
    live = [*new.knowledge.values(), *new.procedural.values()]
    max_access = max((e.access_count for e in live), default=0)
    # Entries the causal graph hangs on keep the active floor; a verified lesson
    # shouldn't fade out from under its own edges.
    linked = {end for e in new.edges for end in (e.src, e.dst)}

    for entry in live:
        entry.lifecycle.salience = compute_salience(
            entry, new.sessions_seen, max_access, weights, load_bearing=entry.id in linked
        )
        entry.lifecycle.state = classify(entry.lifecycle.salience)
        if entry.lifecycle.state == "archived":
            table = new.knowledge if entry.kind == "knowledge" else new.procedural
            del table[entry.id]
            new.archive[entry.id] = entry

    return new
