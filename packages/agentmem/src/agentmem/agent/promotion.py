"""Promote entries from the session bank into the project bank: the smaller,
durable tier that survives across sessions on this project.

Promotion isn't a move: the session-tier original stays exactly where it is, subject
to its own normal decay. What lands in the project bank is a copy, rewritten by the
model as a general rule ("what to do next time") rather than a record of what happened
this one instance. Eligibility and id allocation are system-decided; only the rewrite
goes through the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..config import AgentMemConfig
from ..llm.base import LLMProvider
from ..salience import FLOOR_TAGS
from ..schemas import (
    KNOWLEDGE_TAGS,
    PROCEDURAL_TAGS,
    EntryLifecycle,
    EntryTag,
    MemoryBank,
    MemoryEntry,
)
from .prompts import PROMOTION_SYSTEM, promotion_user_content

DEFAULT_MIN_SESSIONS_LIVED = 3
DEFAULT_PROJECT_MAX = 40


def promotion_eligible(entry: MemoryEntry, bank: MemoryBank, min_sessions_lived: int) -> bool:
    """Lived >= min_sessions_lived sessions, RF > 0, never promoted before, and not
    superseded by another entry."""
    if entry.lifecycle.promoted_from:
        return False  # already promoted once; don't duplicate into the project bank
    if entry.lifecycle.reinforcement <= 0:
        return False
    if bank.sessions_seen - entry.lifecycle.created_session < min_sessions_lived:
        return False
    return not any(e.rel == "supersedes" and e.dst == entry.id for e in bank.edges)


def find_promotion_candidates(
    bank: MemoryBank, min_sessions_lived: int = DEFAULT_MIN_SESSIONS_LIVED
) -> list[MemoryEntry]:
    return [e for e in bank.all_entries() if promotion_eligible(e, bank, min_sessions_lived)]


@dataclass
class PromotionDecision:
    tag: str
    content: str


_LINE_RE = re.compile(
    r"^\[(?P<n>\d+)\]\s+(?:\[(?P<tag>\w+)\]\s*(?P<content>.+)|SKIP)\s*$", re.MULTILINE
)


def parse_promotion(text: str, count: int) -> dict[int, PromotionDecision]:
    """One decision per 1-based candidate index. A candidate the model skips, never
    mentions, or gives no usable content for is absent; the caller treats an absent
    index the same as an explicit SKIP."""
    decisions: dict[int, PromotionDecision] = {}
    for m in _LINE_RE.finditer(text):
        idx = int(m.group("n"))
        if not (1 <= idx <= count) or m.group("content") is None:
            continue
        content = m.group("content").strip()
        if not content:
            continue
        decisions[idx] = PromotionDecision(tag=(m.group("tag") or "other").lower(), content=content)
    return decisions


def _coerce_tag(tag: str, kind: str) -> EntryTag:
    allowed = KNOWLEDGE_TAGS if kind == "knowledge" else PROCEDURAL_TAGS
    for candidate in allowed:
        if tag == candidate:
            return candidate
    return "other"


def _next_project_id(project: MemoryBank, kind: str) -> str:
    if kind == "knowledge":
        project.seq_knowledge += 1
        return f"PK-{project.seq_knowledge:03d}"
    project.seq_procedural += 1
    return f"PP-{project.seq_procedural:03d}"


def apply_promotions(
    session: MemoryBank,
    project: MemoryBank,
    candidates: list[MemoryEntry],
    decisions: dict[int, PromotionDecision],
    session_id: str,
    step: int,
    project_max: int = DEFAULT_PROJECT_MAX,
) -> tuple[MemoryBank, MemoryBank]:
    """Write each decided-on candidate into a copy of the project bank and mark the
    session-tier original as promoted. Pure: neither input is mutated."""
    new_session = session.model_copy(deep=True)
    new_project = project.model_copy(deep=True)

    for i, candidate in enumerate(candidates, start=1):
        decision = decisions.get(i)
        if decision is None:
            continue

        entry_id = _next_project_id(new_project, candidate.kind)
        table = new_project.knowledge if candidate.kind == "knowledge" else new_project.procedural
        table[entry_id] = MemoryEntry(
            id=entry_id,
            kind=candidate.kind,
            tag=_coerce_tag(decision.tag, candidate.kind),
            content=decision.content,
            created_step=step,
            updated_step=step,
            lifecycle=EntryLifecycle(
                tier="project",
                promoted_from=[session_id],
                created_session=new_project.sessions_seen,
                last_touched_session=new_project.sessions_seen,
            ),
        )

        source_table = (
            new_session.knowledge if candidate.kind == "knowledge" else new_session.procedural
        )
        source = source_table.get(candidate.id)
        if source is not None:
            source.lifecycle.promoted_from = [session_id]  # never re-promote this one

    _enforce_project_cap(new_project, project_max)
    return new_session, new_project


def _enforce_project_cap(project: MemoryBank, project_max: int) -> None:
    """Demote the lowest-salience active project entries (never a policy/task one)
    until the bank is back under its combined active-entry budget. Mutates in place.
    """
    while True:
        active = [e for e in project.all_entries() if e.lifecycle.state == "active"]
        if len(active) <= project_max:
            return
        candidates = [e for e in active if e.tag not in FLOOR_TAGS]
        if not candidates:
            return
        victim = min(candidates, key=lambda e: (e.lifecycle.salience, e.id))
        victim.lifecycle.state = "dormant"


def run_promotion(
    provider: LLMProvider,
    config: AgentMemConfig,
    session: MemoryBank,
    project: MemoryBank,
    session_id: str,
    step: int,
) -> tuple[MemoryBank, MemoryBank]:
    """Find candidates, ask the model to rewrite each as a general rule, apply the
    result. Returns (session, project) unchanged, skipping the LLM call entirely,
    when nothing is eligible (the common case).
    """
    candidates = find_promotion_candidates(session, config.continual_min_sessions_lived)
    if not candidates:
        return session, project

    content = promotion_user_content(_render_candidates(candidates))
    resp = provider.complete(
        system=PROMOTION_SYSTEM,
        messages=[{"role": "user", "content": content}],
        tools=None,
        max_tokens=config.max_output_tokens,
    )
    decisions = parse_promotion(resp.text, len(candidates))
    return apply_promotions(
        session, project, candidates, decisions, session_id, step, config.continual_project_max
    )


def _render_candidates(candidates: list[MemoryEntry]) -> str:
    return "\n".join(f"[{i}] {e.render()}" for i, e in enumerate(candidates, start=1))
