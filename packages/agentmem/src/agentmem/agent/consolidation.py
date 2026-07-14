"""Fold near-duplicate entries together and compress recurring clusters into one rule."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..bank import AppliedCall, BankLimits, BankUpdate, apply_tool_calls
from ..config import AgentMemConfig
from ..llm.base import LLMProvider
from ..policy.state_sig import jaccard
from ..schemas import KNOWLEDGE_TAGS, PROCEDURAL_TAGS, EntryTag, MemoryBank, MemoryEntry
from ..tools import DELETE, SAVE_KNOWLEDGE, SAVE_PROCEDURAL, ToolCall
from .prompts import CONSOLIDATION_SYSTEM, consolidation_user_content

MERGE_JACCARD_MIN = 0.6
FUSION_MIN_GROUP = 3


@dataclass
class MergeCandidate:
    a: MemoryEntry
    b: MemoryEntry
    similarity: float


@dataclass
class FusionCandidate:
    entries: list[MemoryEntry]
    signature: str  # the shared `source` the group was grouped by


def find_merge_candidates(bank: MemoryBank) -> list[MergeCandidate]:
    """Same-kind pairs whose content overlaps >= MERGE_JACCARD_MIN.

    Greedy and non-overlapping: once an entry is claimed by a pair, it can't also
    show up in a second pair this pass, so a downstream MERGE/DELETE can never
    target an id another decision already consumed.
    """
    candidates: list[MergeCandidate] = []
    for table in (bank.knowledge, bank.procedural):
        entries = list(table.values())
        claimed: set[str] = set()
        for i, a in enumerate(entries):
            if a.id in claimed:
                continue
            for b in entries[i + 1 :]:
                if b.id in claimed:
                    continue
                sim = jaccard(_tokenize(a.content), _tokenize(b.content))
                if sim >= MERGE_JACCARD_MIN:
                    candidates.append(MergeCandidate(a=a, b=b, similarity=sim))
                    claimed.add(a.id)
                    claimed.add(b.id)
                    break
    return candidates


def find_fusion_candidates(bank: MemoryBank) -> list[FusionCandidate]:
    """Groups of >= FUSION_MIN_GROUP procedural entries sharing a `source`."""
    groups: dict[str, list[MemoryEntry]] = {}
    for entry in bank.procedural.values():
        if entry.source:
            groups.setdefault(entry.source, []).append(entry)
    return [
        FusionCandidate(entries=entries, signature=sig)
        for sig, entries in groups.items()
        if len(entries) >= FUSION_MIN_GROUP
    ]


def _tokenize(content: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", content.lower())


@dataclass
class ConsolidationDecision:
    action: str  # "merge" | "fuse" | "keep"
    tag: str = "other"
    content: str = ""


_LINE_RE = re.compile(
    r"^\[(?P<key>[MF]\d+)\]\s+(?:(?P<action>MERGE|FUSE):\s*(?P<rest>.+)|KEEP)\s*$",
    re.MULTILINE,
)
_TAG_RE = re.compile(r"^\[(\w+)\]\s*(.*)$")


def parse_consolidation(text: str) -> dict[str, ConsolidationDecision]:
    """One decision per candidate key ("M1", "F1", ...). A candidate the model never
    mentions, or mentions with no usable content, is absent, the caller treats an
    absent key the same as an explicit KEEP."""
    decisions: dict[str, ConsolidationDecision] = {}
    for m in _LINE_RE.finditer(text):
        key, action, rest = m.group("key"), m.group("action"), m.group("rest")
        if action is None:
            decisions[key] = ConsolidationDecision(action="keep")
            continue
        tag_match = _TAG_RE.match(rest.strip())
        tag, content = (
            (tag_match.group(1).lower(), tag_match.group(2).strip())
            if tag_match
            else (
                "other",
                rest.strip(),
            )
        )
        if not content:
            continue  # no real content to merge/fuse in; leave it absent (=> keep)
        decisions[key] = ConsolidationDecision(
            action="merge" if action == "MERGE" else "fuse", tag=tag, content=content
        )
    return decisions


def _pick_survivor(a: MemoryEntry, b: MemoryEntry) -> tuple[MemoryEntry, MemoryEntry]:
    """Which of a near-duplicate pair keeps its id: the more established one (more
    injections, then older, then lower id, for a deterministic tiebreak)."""
    keep, drop = sorted([a, b], key=lambda e: (-e.access_count, e.created_step, e.id))
    return keep, drop


def _coerce_tag(tag: str, kind: str) -> EntryTag:
    allowed = KNOWLEDGE_TAGS if kind == "knowledge" else PROCEDURAL_TAGS
    for candidate in allowed:
        if tag == candidate:
            return candidate
    return "other"


def apply_consolidation(
    bank: MemoryBank,
    merges: list[MergeCandidate],
    fusions: list[FusionCandidate],
    decisions: dict[str, ConsolidationDecision],
    step: int,
    limits: BankLimits | None = None,
) -> BankUpdate:
    """Replay MERGE/FUSE decisions through the same tool-call reducer Phase 1 uses,
    so id allocation, tag coercion, and content clipping all stay in one place. The
    only thing that reducer doesn't know how to do is demote fusion sources to
    dormant (never delete), that happens as a small pass afterward."""
    calls: list[ToolCall] = []
    fusion_sources: list[MemoryEntry] = []

    for i, cand in enumerate(merges, start=1):
        d = decisions.get(f"M{i}")
        if d is None or d.action != "merge":
            continue
        keep, drop = _pick_survivor(cand.a, cand.b)
        tool = SAVE_KNOWLEDGE if keep.kind == "knowledge" else SAVE_PROCEDURAL
        calls.append(
            ToolCall(
                name=tool,
                args={"id": keep.id, "tag": _coerce_tag(d.tag, keep.kind), "content": d.content},
            )
        )
        calls.append(ToolCall(name=DELETE, args={"id": drop.id}))

    for i, group in enumerate(fusions, start=1):
        d = decisions.get(f"F{i}")
        if d is None or d.action != "fuse":
            continue
        sources = ",".join(e.id for e in group.entries)
        calls.append(
            ToolCall(
                name=SAVE_PROCEDURAL,
                args={
                    "tag": _coerce_tag(d.tag, "procedural"),
                    "content": d.content,
                    "source": f"fused:{sources}",
                },
            )
        )
        fusion_sources.extend(group.entries)

    update = apply_tool_calls(bank, calls, step, limits)
    for source in fusion_sources:
        entry = update.bank.entry(source.id)
        if entry is not None:
            entry.lifecycle.state = "dormant"
            update.applied.append(
                AppliedCall(
                    tool="(system)",
                    effect="demoted",
                    entry_id=source.id,
                    note="fused into an abstract rule; kept as evidence",
                )
            )
    return update


def run_consolidation(
    provider: LLMProvider, config: AgentMemConfig, bank: MemoryBank, step: int
) -> BankUpdate | None:
    """Find candidates, ask the model what to do with them, apply its decisions.

    Returns None without calling the model at all when there's nothing to
    consolidate, the common case for a bank with no near-duplicates.
    """
    merges = find_merge_candidates(bank)
    fusions = find_fusion_candidates(bank)
    if not merges and not fusions:
        return None

    candidates = _render_candidates(merges, fusions)
    resp = provider.complete(
        system=CONSOLIDATION_SYSTEM,
        messages=[
            {
                "role": "user",
                "content": consolidation_user_content(bank.render_for_agent(), candidates),
            }
        ],
        tools=None,
        max_tokens=config.max_output_tokens,
    )
    decisions = parse_consolidation(resp.text)
    return apply_consolidation(
        bank, merges, fusions, decisions, step, BankLimits.from_config(config)
    )


def _render_candidates(merges: list[MergeCandidate], fusions: list[FusionCandidate]) -> str:
    lines: list[str] = []
    for i, m in enumerate(merges, start=1):
        lines.append(f"[M{i}] {m.a.id} vs {m.b.id} (similarity {m.similarity:.2f})")
        lines.append(f"  {m.a.render()}")
        lines.append(f"  {m.b.render()}")
    for i, f in enumerate(fusions, start=1):
        ids = ", ".join(e.id for e in f.entries)
        lines.append(f"[F{i}] {ids} (source: {f.signature})")
        for e in f.entries:
            lines.append(f"  {e.render()}")
    return "\n".join(lines)
