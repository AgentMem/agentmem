"""Tests for the injector: budget, cooldown, and the injection bookkeeping."""

from __future__ import annotations

from agentmem.agent.phase2 import Bullet
from agentmem.config import AgentMemConfig
from agentmem.injector import HEADER, Injector
from agentmem.schemas import MemoryBank, MemoryEntry


def _bank_with(*ids: str) -> MemoryBank:
    bank = MemoryBank()
    for i in ids:
        table = bank.knowledge if i.startswith("K") else bank.procedural
        table[i] = MemoryEntry(
            id=i,
            kind="knowledge" if i.startswith("K") else "procedural",
            content=f"content of {i}",
            created_step=0,
            updated_step=0,
        )
    return bank


def _bullet(*ids: str) -> Bullet:
    marker = " ".join(f"({i})" for i in ids)
    return Bullet(line=f"{marker} reminder text", cited_ids=list(ids))


def test_build_formats_header_and_bullets() -> None:
    inj = Injector(AgentMemConfig())
    bank = _bank_with("K-001")
    out = inj.build([_bullet("K-001")], bank, step=1)

    assert out is not None
    assert out.text.startswith(HEADER)
    assert "- (K-001) reminder text" in out.text
    assert out.cited_ids == ["K-001"]


def test_build_records_injection_bookkeeping() -> None:
    inj = Injector(AgentMemConfig())
    bank = _bank_with("K-001")
    inj.build([_bullet("K-001")], bank, step=5)

    entry = bank.knowledge["K-001"]
    assert entry.access_count == 1
    assert entry.last_injected_step == 5


def test_cooldown_suppresses_recent_reinjection() -> None:
    config = AgentMemConfig(injector_cooldown_steps=5)
    inj = Injector(config)
    bank = _bank_with("K-001")

    first = inj.build([_bullet("K-001")], bank, step=1)
    assert first is not None
    # Two steps later, still inside the 5-step cooldown -> nothing to say.
    second = inj.build([_bullet("K-001")], bank, step=3)
    assert second is None


def test_cooldown_expires() -> None:
    config = AgentMemConfig(injector_cooldown_steps=5)
    inj = Injector(config)
    bank = _bank_with("K-001")

    inj.build([_bullet("K-001")], bank, step=1)
    later = inj.build([_bullet("K-001")], bank, step=6)  # exactly cooldown steps later
    assert later is not None


def test_tool_failure_bypasses_cooldown() -> None:
    config = AgentMemConfig(injector_cooldown_steps=5)
    inj = Injector(config)
    bank = _bank_with("P-001")

    inj.build([_bullet("P-001")], bank, step=1)
    forced = inj.build([_bullet("P-001")], bank, step=2, bypass_cooldown=True)
    assert forced is not None


def test_max_bullets_cap() -> None:
    config = AgentMemConfig(max_bullets=2)
    inj = Injector(config)
    bank = _bank_with("K-001", "K-002", "K-003")
    out = inj.build([_bullet("K-001"), _bullet("K-002"), _bullet("K-003")], bank, step=1)

    assert out is not None
    assert out.text.count("\n- ") == 2


def test_token_budget_keeps_at_least_one_bullet() -> None:
    # A stingy budget still yields the first grounded bullet; an empty intervention
    # is just silence with overhead.
    config = AgentMemConfig(intervention_token_budget=1)
    inj = Injector(config)
    bank = _bank_with("K-001", "K-002")
    out = inj.build([_bullet("K-001"), _bullet("K-002")], bank, step=1)

    assert out is not None
    assert out.text.count("\n- ") == 1


def test_bullet_citing_dead_entry_is_dropped() -> None:
    inj = Injector(AgentMemConfig())
    bank = _bank_with("K-001")  # note: K-777 does not exist
    out = inj.build([_bullet("K-777")], bank, step=1)
    assert out is None
