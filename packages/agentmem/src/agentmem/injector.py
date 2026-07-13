"""Turn Phase 2's chosen bullets into the reminder the agent sees.

Phase 2 decides what to say; the injector decides how much and how often: at most
`max_bullets` within a token budget, and a per-entry cooldown so we don't repeat the
same reminder every few steps. It also updates the bank's injection bookkeeping.
"""

from __future__ import annotations

from .agent.phase2 import Bullet
from .config import AgentMemConfig
from .schemas import Intervention, MemoryBank, MemoryEntry
from .util import approx_tokens

# Phrased as a statement, not a command: a system-style "You must..." can trip the
# action agent's own prompt-injection defenses.
HEADER = "[AgentMem] Execution-state reminders (transient, from maintained memory):"


class Injector:
    def __init__(self, config: AgentMemConfig) -> None:
        self._cooldown = config.injector_cooldown_steps
        self._max_bullets = config.max_bullets
        self._token_budget = config.intervention_token_budget
        self._causal_enabled = config.causal_enabled
        self._min_confidence = config.causal_min_confidence

    def build(
        self,
        bullets: list[Bullet],
        bank: MemoryBank,
        step: int,
        *,
        bypass_cooldown: bool = False,
        project_bank: MemoryBank | None = None,
    ) -> Intervention | None:
        """Assemble the reminder, or None if nothing survives.

        `bypass_cooldown` lifts the cooldown for this step, which the session sets
        after a tool failure (when repeating a relevant reminder is worth it).
        `project_bank`, if Phase 2 had one to cite from, is checked alongside `bank`
        for cooldown and injection bookkeeping (a PK-/PP- id only exists there).
        """
        if self._causal_enabled:
            # Attach the cause/fix chain to each bullet so a single line carries the
            # "why" without spending a second bullet. It counts toward the budget.
            bullets = [self._with_causal_tail(b, bank, project_bank) for b in bullets]

        kept: list[Bullet] = []
        tokens = approx_tokens(HEADER)

        for bullet in bullets:
            if len(kept) >= self._max_bullets:
                break
            if not bypass_cooldown and self._on_cooldown(bullet, bank, project_bank, step):
                continue
            cost = approx_tokens(bullet.line) + 2  # "- " prefix + newline
            if tokens + cost > self._token_budget and kept:
                break  # out of budget, but keep at least the first bullet
            kept.append(bullet)
            tokens += cost

        if not kept:
            return None

        cited = self._record_injection(kept, bank, project_bank, step)
        text = "\n".join([HEADER, *(f"- {b.line}" for b in kept)])
        return Intervention(text=text, cited_ids=cited, reason=f"cited {', '.join(cited)}")

    def _find(
        self, cid: str, bank: MemoryBank, project_bank: MemoryBank | None
    ) -> MemoryEntry | None:
        return bank.entry(cid) or (project_bank.entry(cid) if project_bank is not None else None)

    def _with_causal_tail(
        self, bullet: Bullet, bank: MemoryBank, project_bank: MemoryBank | None
    ) -> Bullet:
        """Append the high-confidence cause/fix links of the bullet's cited entries."""
        parts: list[str] = []
        for cid in bullet.cited_ids:
            for edge in bank.edges_from(cid):
                if edge.confidence < self._min_confidence:
                    continue
                target = self._find(edge.dst, bank, project_bank)
                if target is None:
                    continue
                parts.append(f"[{edge.rel} {edge.dst}: {_short(target.content)}]")
        if not parts:
            return bullet
        return Bullet(line=f"{bullet.line}  {' '.join(parts[:2])}", cited_ids=bullet.cited_ids)

    def _on_cooldown(
        self, bullet: Bullet, bank: MemoryBank, project_bank: MemoryBank | None, step: int
    ) -> bool:
        """True if every entry the bullet cites is still cooling down."""
        live = [self._find(cid, bank, project_bank) for cid in bullet.cited_ids]
        live_entries = [e for e in live if e is not None]
        if not live_entries:
            return True  # cites only entries that no longer exist
        for entry in live_entries:
            last = entry.last_injected_step
            if last is None or (step - last) >= self._cooldown:
                return False
        return True

    def _record_injection(
        self, kept: list[Bullet], bank: MemoryBank, project_bank: MemoryBank | None, step: int
    ) -> list[str]:
        """Bump access_count / last_injected_step on the entries we cited."""
        cited: list[str] = []
        for bullet in kept:
            for cid in bullet.cited_ids:
                entry = self._find(cid, bank, project_bank)
                if entry is None:
                    continue
                entry.access_count += 1
                entry.last_injected_step = step
                if cid not in cited:
                    cited.append(cid)
        return cited


def _short(text: str, words: int = 8) -> str:
    parts = text.split()
    return " ".join(parts[:words]) + ("..." if len(parts) > words else "")
