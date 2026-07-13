"""Tests for the schema render helpers and JSON round-trip."""

from __future__ import annotations

from agentmem.schemas import EntryLifecycle, Event, MemoryBank, MemoryEntry, render_tiered_for_agent


def _bank() -> MemoryBank:
    bank = MemoryBank(status="wiring up auth")
    bank.knowledge["K-001"] = MemoryEntry(
        id="K-001",
        kind="knowledge",
        tag="task",
        content="keep the public API stable",
        created_step=1,
        updated_step=1,
    )
    bank.procedural["P-001"] = MemoryEntry(
        id="P-001",
        kind="procedural",
        tag="fix",
        content="pin torch to 2.2",
        created_step=2,
        updated_step=3,
        access_count=2,
    )
    return bank


def test_render_for_agent_is_id_first() -> None:
    text = _bank().render_for_agent()
    assert "K-001 [task] keep the public API stable" in text
    assert "STATUS: wiring up auth" in text


def test_render_full_shows_bookkeeping() -> None:
    text = _bank().render_full()
    assert "used 2x" in text  # P-001's access_count surfaces here


def test_event_render_marks_failures() -> None:
    ok = Event(kind="tool_result", tool_name="bash", ok=True, text="passed")
    bad = Event(kind="tool_result", tool_name="bash", ok=False, text="exit 1")
    assert "ok" in ok.render()
    assert "FAILED" in bad.render()


def test_bank_json_round_trip() -> None:
    bank = _bank()
    assert MemoryBank.model_validate_json(bank.model_dump_json()) == bank


def test_render_for_agent_hides_dormant_only_when_asked() -> None:
    bank = _bank()
    bank.knowledge["K-001"].lifecycle = EntryLifecycle(state="dormant")

    with_dormant = bank.render_for_agent()
    without_dormant = bank.render_for_agent(include_dormant=False)

    assert "K-001" in with_dormant  # Phase 1 can still revive it
    assert "K-001" not in without_dormant  # Phase 2 never cites it
    assert "P-001" in without_dormant  # the still-active entry is untouched


def test_has_citable_entries_respects_dormant_flag() -> None:
    bank = _bank()
    bank.knowledge["K-001"].lifecycle = EntryLifecycle(state="dormant")
    bank.procedural["P-001"].lifecycle = EntryLifecycle(state="dormant")

    assert bank.has_citable_entries(include_dormant=True) is True
    assert bank.has_citable_entries(include_dormant=False) is False


def test_has_citable_entries_false_for_empty_bank() -> None:
    assert MemoryBank().has_citable_entries() is False


def _entry(id_: str, salience: float, kind: str = "knowledge") -> MemoryEntry:
    return MemoryEntry(
        id=id_,
        kind=kind,
        content=id_,
        created_step=1,
        updated_step=1,
        lifecycle=EntryLifecycle(salience=salience),
    )


def test_render_for_agent_cap_keeps_the_highest_salience_entries() -> None:
    bank = MemoryBank(
        knowledge={
            "K-001": _entry("K-001", 0.9),
            "K-002": _entry("K-002", 0.1),
        },
        procedural={"P-001": _entry("P-001", 0.5, kind="procedural")},
    )
    text = bank.render_for_agent(cap=2)
    assert "K-001" in text
    assert "P-001" in text
    assert "K-002" not in text  # lowest salience, cut by the cap


def test_render_tiered_for_agent_falls_back_to_plain_render_without_a_project_bank() -> None:
    bank = MemoryBank(knowledge={"K-001": _entry("K-001", 1.0)})
    assert render_tiered_for_agent(bank, None) == bank.render_for_agent(cap=12)


def test_render_tiered_for_agent_puts_project_memory_first() -> None:
    session = MemoryBank(knowledge={"K-001": _entry("K-001", 1.0)})
    project = MemoryBank(knowledge={"PK-001": _entry("PK-001", 1.0)})
    text = render_tiered_for_agent(session, project)
    assert text.index("PROJECT MEMORY") < text.index("PK-001") < text.index("K-001")


def test_render_tiered_for_agent_caps_the_project_tier_independently() -> None:
    project = MemoryBank(
        knowledge={
            "PK-001": _entry("PK-001", 0.9),
            "PK-002": _entry("PK-002", 0.1),
        }
    )
    text = render_tiered_for_agent(MemoryBank(), project, project_cap=1)
    assert "PK-001" in text
    assert "PK-002" not in text


def test_render_tiered_for_agent_skips_the_project_header_when_empty() -> None:
    text = render_tiered_for_agent(MemoryBank(), MemoryBank())
    assert "PROJECT MEMORY" not in text
