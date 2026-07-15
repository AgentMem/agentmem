"""Shared data models: the memory bank, its entries, events, and step results."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

EntryKind = Literal["knowledge", "procedural"]

# The tool schemas restrict which tags each kind may use; this is just the union.
EntryTag = Literal[
    "env", "path", "task", "bug", "perf", "attempt", "fix", "diagnosis", "policy", "other"
]
KNOWLEDGE_TAGS: tuple[EntryTag, ...] = ("env", "path", "task", "policy", "other")
PROCEDURAL_TAGS: tuple[EntryTag, ...] = ("attempt", "fix", "diagnosis", "bug", "perf", "other")

EventKind = Literal["message", "tool_call", "tool_result", "observation"]
Decision = Literal["silent", "inject"]

# Causal/logical relations between two entries, e.g. "P-014 caused_by K-007".
CausalRel = Literal["caused_by", "fixed_by", "rules_out", "blocks", "verifies", "supersedes"]
CAUSAL_RELS: tuple[CausalRel, ...] = (
    "caused_by",
    "fixed_by",
    "rules_out",
    "blocks",
    "verifies",
    "supersedes",
)

LifecycleState = Literal["active", "dormant", "archived"]
MemoryTier = Literal["session", "project", "playbook"]


class Event(BaseModel):
    """One thing that happened in the action agent's trajectory.

    ok=False is what the tool-failure trigger watches for.
    """

    kind: EventKind = "message"
    role: str = ""
    text: str = ""
    tool_name: str | None = None
    ok: bool = True
    source: str | None = None  # e.g. "user_msg:3", "tool:pytest"

    def render(self) -> str:
        """One line for the memory agent's window."""
        if self.kind == "tool_call":
            return f"[tool_call {self.tool_name}] {self.text}".rstrip()
        if self.kind == "tool_result":
            status = "ok" if self.ok else "FAILED"
            return f"[tool_result {self.tool_name} {status}] {self.text}".rstrip()
        if self.kind == "observation":
            return f"[obs] {self.text}"
        prefix = f"{self.role}: " if self.role else ""
        return f"{prefix}{self.text}"


class EntryLifecycle(BaseModel):
    """Where an entry sits on the active -> dormant -> archived spectrum, and which
    memory tier (session/project/playbook) it's promoted into."""

    state: LifecycleState = "active"
    salience: float = 1.0
    reinforcement: float = 0.0  # in [-1, 1]; the evaluator moves it by how useful this entry proved
    tier: MemoryTier = "session"
    promoted_from: list[str] = Field(default_factory=list)  # source session ids
    last_touched_session: int = 0  # drives the recency term of the salience score
    created_session: int = 0  # how long it has lived, for promotion eligibility


class MemoryEntry(BaseModel):
    id: str  # "K-001" / "P-014", allocated by the system
    kind: EntryKind
    tag: EntryTag = "other"
    content: str
    created_step: int
    updated_step: int
    access_count: int = 0  # times injected; drives eviction and the cooldown
    last_injected_step: int | None = None
    source: str | None = None
    lifecycle: EntryLifecycle = Field(default_factory=EntryLifecycle)

    def render(self) -> str:
        return f"{self.id} [{self.tag}] {self.content}"


class MemoryEdge(BaseModel):
    """A causal/logical link between two entries. `evidence_step` is where the model
    claims it saw the evidence, and is required so links aren't invented."""

    src: str
    dst: str
    rel: CausalRel
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_step: int

    def render(self) -> str:
        return f"{self.src} --{self.rel}--> {self.dst} (c={self.confidence:.1f})"


class MemoryBank(BaseModel):
    status: str = ""
    knowledge: dict[str, MemoryEntry] = Field(default_factory=dict)
    procedural: dict[str, MemoryEntry] = Field(default_factory=dict)
    edges: list[MemoryEdge] = Field(default_factory=list)  # causal links between entries
    archive: dict[str, MemoryEntry] = Field(default_factory=dict)  # cold storage, out of render
    version: int = 0  # bumped on every applied edit
    sessions_seen: int = 0  # bumped once per logical session; drives salience decay
    # Monotonic id counters. Ids are never reused, even after an entry is deleted.
    seq_knowledge: int = 0
    seq_procedural: int = 0

    def entry(self, entry_id: str) -> MemoryEntry | None:
        return self.knowledge.get(entry_id) or self.procedural.get(entry_id)

    def all_entries(self) -> list[MemoryEntry]:
        return [*self.knowledge.values(), *self.procedural.values()]

    def edges_from(self, entry_id: str) -> list[MemoryEdge]:
        return [e for e in self.edges if e.src == entry_id]

    def is_empty(self) -> bool:
        return not self.status and not self.knowledge and not self.procedural

    def has_citable_entries(self, *, include_dormant: bool = True) -> bool:
        """Whether there's anything a reminder could ground itself in."""
        return bool(
            self._visible(self.knowledge, include_dormant)
            or self._visible(self.procedural, include_dormant)
        )

    def render_for_agent(self, *, include_dormant: bool = True, cap: int | None = None) -> str:
        """Compact, id-first render for the Phase 1 / Phase 2 prompts.

        Phase 1 sees dormant entries too (`include_dormant=True`, the default) so it
        can revive one by saving over its id. Phase 2 never should: a dormant entry
        already backed off from active use, so it shouldn't get cited in a reminder;
        pass `include_dormant=False`. Archived entries never show either way: they've
        already left `knowledge`/`procedural` for `archive`.

        `cap`, if given, keeps only the top-salience entries (combined across
        knowledge and procedural). It's the guardrail against a big bank drowning the
        model in retrieval competition.
        """
        knowledge = self._visible(self.knowledge, include_dormant)
        procedural = self._visible(self.procedural, include_dormant)
        if cap is not None:
            knowledge, procedural = self._cap_by_salience(knowledge, procedural, cap)

        lines: list[str] = []
        lines.append("STATUS: " + (self.status.strip() or "(empty)"))
        lines.append("")
        lines.append("KNOWLEDGE:" if knowledge else "KNOWLEDGE: (empty)")
        for e in knowledge:
            lines.append(f"  {e.render()}")
        lines.append("")
        lines.append("PROCEDURAL:" if procedural else "PROCEDURAL: (empty)")
        for e in procedural:
            lines.append(f"  {e.render()}")
        if self.edges:
            lines.append("")
            lines.append("CAUSAL LINKS:")
            for edge in self.edges:
                lines.append(f"  {edge.render()}")
        return "\n".join(lines)

    @staticmethod
    def _visible(table: dict[str, MemoryEntry], include_dormant: bool) -> list[MemoryEntry]:
        if include_dormant:
            return list(table.values())
        return [e for e in table.values() if e.lifecycle.state != "dormant"]

    @staticmethod
    def _cap_by_salience(
        knowledge: list[MemoryEntry], procedural: list[MemoryEntry], cap: int
    ) -> tuple[list[MemoryEntry], list[MemoryEntry]]:
        pool = sorted(knowledge + procedural, key=lambda e: e.lifecycle.salience, reverse=True)
        keep = {e.id for e in pool[:cap]}
        return [e for e in knowledge if e.id in keep], [e for e in procedural if e.id in keep]

    def render_full(self) -> str:
        """Human-readable dump for `agentmem bank` and inspection."""
        out: list[str] = [f"Memory bank (version {self.version})", "=" * 40]
        out.append(f"\nStatus:\n  {self.status.strip() or '(empty)'}")
        for title, entries in (("Knowledge", self.knowledge), ("Procedural", self.procedural)):
            out.append(f"\n{title} ({len(entries)}):")
            if not entries:
                out.append("  (empty)")
            for e in entries.values():
                seen = f", used {e.access_count}x" if e.access_count else ""
                out.append(
                    f"  {e.render()}  (step {e.updated_step}{seen}, "
                    f"{e.lifecycle.state} S={e.lifecycle.salience:.2f})"
                )
        out.append(f"\nCausal links ({len(self.edges)}):")
        for edge in self.edges or []:
            out.append(f"  {edge.render()}  (from step {edge.evidence_step})")
        if not self.edges:
            out.append("  (none)")
        if self.archive:
            out.append(f"\nArchived ({len(self.archive)}):")
            for e in self.archive.values():
                out.append(f"  {e.render()}  (S={e.lifecycle.salience:.2f})")
        return "\n".join(out)


def render_tiered_for_agent(
    session: MemoryBank,
    project: MemoryBank | None = None,
    *,
    include_dormant: bool = True,
    session_cap: int = 12,
    project_cap: int = 8,
) -> str:
    """Merge the project and session tiers into one render for Phase 1/2: project
    first (it's the durable, cross-session layer), each tier capped to its top
    entries by salience. With no project bank (nothing promoted yet, or continual
    memory off), this is just the session tier, capped the same way.
    """
    lines: list[str] = []
    if project is not None and not project.is_empty():
        lines.append("PROJECT MEMORY (durable, cross-session):")
        pool = MemoryBank._visible(project.knowledge, include_dormant) + MemoryBank._visible(
            project.procedural, include_dormant
        )
        pool.sort(key=lambda e: e.lifecycle.salience, reverse=True)
        for e in pool[:project_cap]:
            lines.append(f"  {e.render()}")
        lines.append("")

    lines.append(session.render_for_agent(include_dormant=include_dormant, cap=session_cap))
    return "\n".join(lines)


class Intervention(BaseModel):
    """A reminder chosen by Phase 2, already formatted by the injector."""

    text: str
    cited_ids: list[str] = Field(default_factory=list)
    reason: str = ""
    # What each cited entry said at the moment it was shown to the agent. Ids alone
    # aren't enough to answer "why did it say that?" later: consolidation and capacity
    # eviction retire entries, and a citation to a retired id resolves to nothing.
    cited_snapshot: dict[str, str] = Field(default_factory=dict)


class TokenUsage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    model: str = ""

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            latency_ms=self.latency_ms + other.latency_ms,
            model=self.model or other.model,
        )


class StepResult(BaseModel):
    """The outcome of one memory-step."""

    step: int
    bank_version: int
    decision: Decision
    intervention: Intervention | None = None
    usage: TokenUsage = Field(default_factory=TokenUsage)
