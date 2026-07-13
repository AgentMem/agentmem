"""The bank reducer: apply a batch of tool calls, get a new bank back.

Pure and total: it never mutates its input, never raises on bad input (a
memory-step must not crash the action loop), and caps growth by evicting the
least-useful entries when the bank is full.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from .salience import ACTIVE_MIN, FLOOR_TAGS, SalienceWeights
from .schemas import (
    CAUSAL_RELS,
    KNOWLEDGE_TAGS,
    PROCEDURAL_TAGS,
    EntryLifecycle,
    EntryTag,
    MemoryBank,
    MemoryEdge,
    MemoryEntry,
)
from .tools import DELETE, LINK, SAVE_KNOWLEDGE, SAVE_PROCEDURAL, UPDATE_STATUS, ToolCall
from .util import clip_to_tokens


@dataclass(frozen=True)
class BankLimits:
    """Budget and scoring knobs, split out so bank.py doesn't depend on the config
    module."""

    status_tokens: int = 150
    entry_tokens: int = 60
    max_knowledge: int = 30
    max_procedural: int = 30
    max_edges: int = 40
    max_edges_per_src: int = 2
    continual_enabled: bool = True
    salience_weights: SalienceWeights = SalienceWeights()

    @classmethod
    def from_config(cls, config: object) -> BankLimits:
        # Duck-typed so tests can pass anything with the right attributes.
        return cls(
            status_tokens=getattr(config, "status_token_budget", cls.status_tokens),
            entry_tokens=getattr(config, "entry_token_budget", cls.entry_tokens),
            max_knowledge=getattr(config, "max_knowledge", cls.max_knowledge),
            max_procedural=getattr(config, "max_procedural", cls.max_procedural),
            max_edges=getattr(config, "max_edges", cls.max_edges),
            max_edges_per_src=getattr(config, "max_edges_per_src", cls.max_edges_per_src),
            continual_enabled=getattr(config, "continual_enabled", cls.continual_enabled),
            salience_weights=SalienceWeights.from_config(config),
        )


Effect = Literal[
    "status_updated",
    "created",
    "updated",
    "deleted",
    "rejected",
    "evicted",
    "demoted",
    "revived",
    "linked",
    "unlinked",
]


class AppliedCall(BaseModel):
    """One line in the audit log of what a step did to the bank."""

    tool: str
    effect: Effect
    entry_id: str | None = None
    note: str = ""


class BankUpdate(BaseModel):
    bank: MemoryBank
    applied: list[AppliedCall]

    @property
    def changed(self) -> bool:
        return any(a.effect != "rejected" for a in self.applied)


def _next_id(bank: MemoryBank, kind: Literal["knowledge", "procedural"]) -> str:
    """Next never-before-used id for `kind`; advances the counter."""
    if kind == "knowledge":
        bank.seq_knowledge += 1
        return f"K-{bank.seq_knowledge:03d}"
    bank.seq_procedural += 1
    return f"P-{bank.seq_procedural:03d}"


def _coerce_tag(tag: str, allowed: tuple[EntryTag, ...]) -> EntryTag:
    # Models improvise tags; downgrade to "other" rather than reject the content.
    for candidate in allowed:
        if tag == candidate:
            return candidate
    return "other"


def apply_tool_calls(
    bank: MemoryBank,
    calls: list[ToolCall],
    step: int,
    limits: BankLimits | None = None,
) -> BankUpdate:
    """Apply `calls` to a copy of `bank`; return the new bank and an audit log."""
    limits = limits or BankLimits()
    new = bank.model_copy(deep=True)
    log: list[AppliedCall] = []

    for call in calls:
        if call.name == UPDATE_STATUS:
            new.status = clip_to_tokens(
                str(call.args.get("status", "")).strip(), limits.status_tokens
            )
            log.append(AppliedCall(tool=call.name, effect="status_updated"))
        elif call.name in (SAVE_KNOWLEDGE, SAVE_PROCEDURAL):
            log.append(_apply_save(new, call, step, limits))
        elif call.name == DELETE:
            log.append(_apply_delete(new, call))
        elif call.name == LINK:
            log.append(_apply_link(new, call, limits))
        else:
            log.append(AppliedCall(tool=call.name, effect="rejected", note="unknown tool"))

    log.extend(_enforce_capacity(new, limits, step))

    if any(a.effect != "rejected" for a in log):
        new.version += 1

    return BankUpdate(bank=new, applied=log)


def _apply_save(new: MemoryBank, call: ToolCall, step: int, limits: BankLimits) -> AppliedCall:
    kind: Literal["knowledge", "procedural"] = (
        "knowledge" if call.name == SAVE_KNOWLEDGE else "procedural"
    )
    table = new.knowledge if kind == "knowledge" else new.procedural
    allowed = KNOWLEDGE_TAGS if kind == "knowledge" else PROCEDURAL_TAGS

    content = clip_to_tokens(str(call.args.get("content", "")).strip(), limits.entry_tokens)
    if not content:
        return AppliedCall(tool=call.name, effect="rejected", note="empty content")

    tag = _coerce_tag(str(call.args.get("tag", "other")), allowed)
    given_id = call.args.get("id")

    # A known id updates in place; anything else creates with a fresh system id.
    if given_id and given_id in table:
        entry = table[given_id]
        entry.content = content
        entry.tag = tag
        entry.updated_step = step
        entry.lifecycle.last_touched_session = new.sessions_seen
        # A fresh save always counts as a revival, even if it was dormant.
        entry.lifecycle.state = "active"
        entry.lifecycle.salience = max(entry.lifecycle.salience, ACTIVE_MIN)
        return AppliedCall(tool=call.name, effect="updated", entry_id=given_id)

    entry_id = _next_id(new, kind)
    table[entry_id] = MemoryEntry(
        id=entry_id,
        kind=kind,
        tag=tag,
        content=content,
        created_step=step,
        updated_step=step,
        source=call.args.get("source"),
        lifecycle=EntryLifecycle(
            created_session=new.sessions_seen, last_touched_session=new.sessions_seen
        ),
    )
    note = "unknown id, created new" if given_id else ""
    return AppliedCall(tool=call.name, effect="created", entry_id=entry_id, note=note)


def _apply_delete(new: MemoryBank, call: ToolCall) -> AppliedCall:
    entry_id = str(call.args.get("id", ""))
    if entry_id in new.knowledge:
        del new.knowledge[entry_id]
    elif entry_id in new.procedural:
        del new.procedural[entry_id]
    elif entry_id in new.archive:
        del new.archive[entry_id]
    else:
        return AppliedCall(tool=call.name, effect="rejected", entry_id=entry_id, note="no such id")
    # An edge to or from a gone entry is meaningless, so drop it.
    new.edges = [e for e in new.edges if entry_id not in (e.src, e.dst)]
    return AppliedCall(tool=call.name, effect="deleted", entry_id=entry_id)


def _apply_link(new: MemoryBank, call: ToolCall, limits: BankLimits) -> AppliedCall:
    src = str(call.args.get("src", ""))
    dst = str(call.args.get("dst", ""))
    rel = str(call.args.get("rel", ""))

    if call.args.get("remove"):
        kept = [e for e in new.edges if not (e.src == src and e.dst == dst and e.rel == rel)]
        if len(kept) == len(new.edges):
            return AppliedCall(tool=call.name, effect="rejected", note="no such edge")
        new.edges = kept
        return AppliedCall(tool=call.name, effect="unlinked", entry_id=src)

    reason = _link_rejection(new, src, dst, rel, limits)
    if reason:
        return AppliedCall(tool=call.name, effect="rejected", note=reason)

    evidence_step = call.args.get("evidence_step")
    if not isinstance(evidence_step, int):
        return AppliedCall(tool=call.name, effect="rejected", note="missing evidence_step")
    confidence = max(0.0, min(1.0, _as_float(call.args.get("confidence"))))

    new.edges.append(
        MemoryEdge(src=src, dst=dst, rel=rel, confidence=confidence, evidence_step=evidence_step)  # type: ignore[arg-type]
    )
    return AppliedCall(tool=call.name, effect="linked", entry_id=src, note=f"{src} {rel} {dst}")


def _link_rejection(
    new: MemoryBank, src: str, dst: str, rel: str, limits: BankLimits
) -> str | None:
    if src == dst:
        return "self-loop"
    if new.entry(src) is None or new.entry(dst) is None:
        return "endpoint missing"
    if rel not in CAUSAL_RELS:
        return "unknown relation"
    if any(e.src == src and e.dst == dst and e.rel == rel for e in new.edges):
        return "duplicate edge"
    if len(new.edges) >= limits.max_edges:
        return "edge budget full"
    if len(new.edges_from(src)) >= limits.max_edges_per_src:
        return "too many links from this entry"
    return None


def _as_float(value: object) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def _enforce_capacity(new: MemoryBank, limits: BankLimits, step: int) -> list[AppliedCall]:
    """Shrink down to the entry-count budget, least-useful first.

    With continual memory on, the cap only counts `active` entries: the victim is the
    lowest-salience one (ties broken by fewest injections, then oldest, then id) and
    it's demoted to `dormant` rather than removed, so nothing is ever deleted just for
    being unpopular. `policy`/`task` entries are exempt (see salience.py).
    Off, this is the original hard-delete behavior, unchanged.
    """
    evicted: list[AppliedCall] = []
    for table, cap in (
        (new.knowledge, limits.max_knowledge),
        (new.procedural, limits.max_procedural),
    ):
        while _pressure_count(table, limits.continual_enabled) > cap:
            candidates = [
                e
                for e in table.values()
                if not limits.continual_enabled
                or (e.lifecycle.state == "active" and e.tag not in FLOOR_TAGS)
            ]
            if not candidates:
                break  # nothing left that's eligible to give ground

            if limits.continual_enabled:
                victim = min(
                    candidates,
                    key=lambda e: (e.lifecycle.salience, e.access_count, e.updated_step, e.id),
                )
                victim.lifecycle.state = "dormant"
                evicted.append(
                    AppliedCall(
                        tool="(system)",
                        effect="demoted",
                        entry_id=victim.id,
                        note=f"over capacity ({cap}); lowest-salience demoted at step {step}",
                    )
                )
            else:
                victim = min(candidates, key=lambda e: (e.access_count, e.updated_step, e.id))
                del table[victim.id]
                evicted.append(
                    AppliedCall(
                        tool="(system)",
                        effect="evicted",
                        entry_id=victim.id,
                        note=f"over capacity ({cap}); least-used evicted at step {step}",
                    )
                )
    return evicted


def _pressure_count(table: dict[str, MemoryEntry], continual_enabled: bool) -> int:
    """How many entries count against the capacity cap.

    Off, every entry counts (the old behavior). On, only `active` entries do;
    `dormant` ones already backed off and shouldn't be evicted twice.
    """
    if not continual_enabled:
        return len(table)
    return sum(1 for e in table.values() if e.lifecycle.state == "active")


def budget_warnings(bank: MemoryBank, limits: BankLimits | None = None) -> list[str]:
    """Prompt nudges to consolidate before the bank hits its limits."""
    limits = limits or BankLimits()
    warnings: list[str] = []
    if len(bank.knowledge) >= limits.max_knowledge - 2:
        warnings.append(
            f"Knowledge is near capacity ({len(bank.knowledge)}/{limits.max_knowledge}); "
            "merge or delete before adding."
        )
    if len(bank.procedural) >= limits.max_procedural - 2:
        warnings.append(
            f"Procedural is near capacity ({len(bank.procedural)}/{limits.max_procedural}); "
            "merge or delete before adding."
        )
    return warnings
