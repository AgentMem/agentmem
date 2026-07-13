"""Golden + property tests for the bank reducer.

`apply_tool_calls` is the function everything else trusts to be pure and
deterministic, so this file leans on it: exact expected banks for known inputs, plus
the invariants (purity, no id reuse, capped growth).
"""

from __future__ import annotations

from agentmem.bank import BankLimits, apply_tool_calls, budget_warnings
from agentmem.schemas import EntryLifecycle, MemoryBank, MemoryEntry
from agentmem.tools import DELETE, SAVE_KNOWLEDGE, SAVE_PROCEDURAL, UPDATE_STATUS, ToolCall


def _call(name: str, **args: object) -> ToolCall:
    # block_id is irrelevant to the reducer; the phase-1 loop uses it, not us.
    return ToolCall(name=name, args=args)


def test_create_allocates_sequential_ids() -> None:
    bank = MemoryBank()
    calls = [
        _call(SAVE_KNOWLEDGE, tag="env", content="Python 3.11 venv at .venv"),
        _call(SAVE_KNOWLEDGE, tag="path", content="tests live in tests/"),
        _call(SAVE_PROCEDURAL, tag="attempt", content="pip install torch OOM'd"),
    ]
    out = apply_tool_calls(bank, calls, step=1)

    assert list(out.bank.knowledge) == ["K-001", "K-002"]
    assert list(out.bank.procedural) == ["P-001"]
    assert out.bank.knowledge["K-001"].content == "Python 3.11 venv at .venv"
    assert out.bank.knowledge["K-001"].tag == "env"
    assert out.bank.version == 1
    assert out.changed is True


def test_apply_is_pure_input_untouched() -> None:
    bank = MemoryBank()
    apply_tool_calls(bank, [_call(SAVE_KNOWLEDGE, tag="env", content="x")], step=1)
    # The original must be untouched: no id counters bumped, nothing added.
    assert bank == MemoryBank()


def test_apply_is_deterministic() -> None:
    calls = [
        _call(SAVE_KNOWLEDGE, tag="env", content="a"),
        _call(SAVE_PROCEDURAL, tag="fix", content="b"),
        _call(UPDATE_STATUS, status="halfway there"),
    ]
    first = apply_tool_calls(MemoryBank(), calls, step=3)
    second = apply_tool_calls(MemoryBank(), calls, step=3)
    assert first.bank == second.bank


def test_upsert_by_existing_id_updates_in_place() -> None:
    out = apply_tool_calls(
        MemoryBank(), [_call(SAVE_PROCEDURAL, tag="attempt", content="first try")], step=1
    )
    out = apply_tool_calls(
        out.bank,
        [_call(SAVE_PROCEDURAL, id="P-001", tag="diagnosis", content="root cause found")],
        step=2,
    )
    assert list(out.bank.procedural) == ["P-001"]  # no new entry
    entry = out.bank.procedural["P-001"]
    assert entry.content == "root cause found"
    assert entry.tag == "diagnosis"
    assert entry.created_step == 1 and entry.updated_step == 2


def test_unknown_id_creates_new_and_notes_it() -> None:
    out = apply_tool_calls(
        MemoryBank(),
        [_call(SAVE_KNOWLEDGE, id="K-999", tag="env", content="fresh")],
        step=1,
    )
    assert list(out.bank.knowledge) == ["K-001"]
    assert out.applied[0].effect == "created"
    assert "unknown id" in out.applied[0].note


def test_delete_existing_and_missing() -> None:
    seeded = apply_tool_calls(
        MemoryBank(), [_call(SAVE_KNOWLEDGE, tag="env", content="x")], step=1
    ).bank
    out = apply_tool_calls(seeded, [_call(DELETE, id="K-001"), _call(DELETE, id="K-404")], step=2)

    assert out.bank.knowledge == {}
    assert out.applied[0].effect == "deleted"
    assert out.applied[1].effect == "rejected"
    assert out.applied[1].note == "no such id"


def test_ids_are_never_reused_after_delete() -> None:
    out = apply_tool_calls(MemoryBank(), [_call(SAVE_KNOWLEDGE, tag="env", content="one")], step=1)
    out = apply_tool_calls(out.bank, [_call(DELETE, id="K-001")], step=2)
    out = apply_tool_calls(out.bank, [_call(SAVE_KNOWLEDGE, tag="env", content="two")], step=3)
    # The counter moved on; the new entry is K-002, not a recycled K-001.
    assert list(out.bank.knowledge) == ["K-002"]


def test_status_is_clipped_to_budget() -> None:
    limits = BankLimits(status_tokens=5)  # ~20 chars
    long_status = "word " * 50
    out = apply_tool_calls(
        MemoryBank(), [_call(UPDATE_STATUS, status=long_status)], step=1, limits=limits
    )
    assert out.bank.status.endswith("...")
    assert len(out.bank.status) <= 5 * 4 + len(" ...")


def test_bad_tag_falls_back_to_other() -> None:
    # "attempt" is a procedural tag; using it on a knowledge save is invalid, so it
    # degrades to "other" rather than dropping the (useful) content.
    out = apply_tool_calls(
        MemoryBank(), [_call(SAVE_KNOWLEDGE, tag="attempt", content="x")], step=1
    )
    assert out.bank.knowledge["K-001"].tag == "other"


def test_empty_content_is_rejected() -> None:
    out = apply_tool_calls(MemoryBank(), [_call(SAVE_KNOWLEDGE, tag="env", content="   ")], step=1)
    assert out.bank.knowledge == {}
    assert out.applied[0].effect == "rejected"


def test_no_changes_does_not_bump_version() -> None:
    out = apply_tool_calls(MemoryBank(version=7), [_call(DELETE, id="nope")], step=1)
    assert out.bank.version == 7
    assert out.changed is False


def _three_entries() -> MemoryBank:
    return MemoryBank(
        seq_knowledge=3,
        knowledge={
            "K-001": MemoryEntry(
                id="K-001",
                kind="knowledge",
                content="old, unused",
                created_step=1,
                updated_step=1,
                access_count=0,
            ),
            "K-002": MemoryEntry(
                id="K-002",
                kind="knowledge",
                content="used once",
                created_step=2,
                updated_step=2,
                access_count=1,
            ),
            "K-003": MemoryEntry(
                id="K-003",
                kind="knowledge",
                content="newest, unused",
                created_step=3,
                updated_step=3,
                access_count=0,
            ),
        },
    )


def test_capacity_evicts_least_used_then_oldest_continual_disabled() -> None:
    limits = BankLimits(max_knowledge=2, continual_enabled=False)
    # Already 3 entries with a cap of 2; adding one forces two evictions.
    out = apply_tool_calls(
        _three_entries(),
        [ToolCall(name=SAVE_KNOWLEDGE, args={"tag": "env", "content": "new"})],
        step=4,
        limits=limits,
    )

    assert len(out.bank.knowledge) == 2
    # K-002 (used once) survives; the two never-used ones are evicted oldest-first
    # among equals, so K-001 goes before K-003... but both unused go before the new
    # entry and the used one. Survivors: the used entry and the freshly added one.
    assert "K-002" in out.bank.knowledge
    evicted = {a.entry_id for a in out.applied if a.effect == "evicted"}
    assert evicted == {"K-001", "K-003"}


def test_capacity_demotes_lowest_salience_when_continual_enabled() -> None:
    # continual_enabled defaults to True: nothing is deleted, the same two victims
    # are just demoted to dormant and stay in the dict.
    limits = BankLimits(max_knowledge=2)
    out = apply_tool_calls(
        _three_entries(),
        [ToolCall(name=SAVE_KNOWLEDGE, args={"tag": "env", "content": "new"})],
        step=4,
        limits=limits,
    )

    assert len(out.bank.knowledge) == 4  # nothing removed, just demoted
    demoted = {a.entry_id for a in out.applied if a.effect == "demoted"}
    assert demoted == {"K-001", "K-003"}
    assert out.bank.knowledge["K-001"].lifecycle.state == "dormant"
    assert out.bank.knowledge["K-003"].lifecycle.state == "dormant"
    assert out.bank.knowledge["K-002"].lifecycle.state == "active"


def test_capacity_demotion_spares_policy_and_task_tags() -> None:
    # Floor-protected entries never get chosen as the demotion victim, even at S=1.0
    # parity with everything else; capacity pressure has to fall on something else.
    bank = MemoryBank(
        seq_knowledge=2,
        knowledge={
            "K-001": MemoryEntry(
                id="K-001",
                kind="knowledge",
                tag="policy",
                content="never break prod",
                created_step=1,
                updated_step=1,
            ),
            "K-002": MemoryEntry(
                id="K-002",
                kind="knowledge",
                tag="env",
                content="venv at .venv",
                created_step=1,
                updated_step=1,
            ),
        },
    )
    out = apply_tool_calls(
        bank,
        [ToolCall(name=SAVE_KNOWLEDGE, args={"tag": "env", "content": "new"})],
        step=2,
        limits=BankLimits(max_knowledge=2),
    )
    demoted = {a.entry_id for a in out.applied if a.effect == "demoted"}
    assert demoted == {"K-002"}
    assert out.bank.knowledge["K-001"].lifecycle.state == "active"


def test_budget_warnings_fire_near_capacity() -> None:
    limits = BankLimits(max_knowledge=3)
    bank = MemoryBank(
        knowledge={
            f"K-00{i}": MemoryEntry(
                id=f"K-00{i}", kind="knowledge", content="x", created_step=i, updated_step=i
            )
            for i in range(1, 3)
        }
    )
    warnings = budget_warnings(bank, limits)
    assert warnings and "near capacity" in warnings[0]


def test_save_with_known_id_revives_a_dormant_entry() -> None:
    bank = MemoryBank(
        knowledge={
            "K-001": MemoryEntry(
                id="K-001",
                kind="knowledge",
                content="stale",
                created_step=1,
                updated_step=1,
                lifecycle=EntryLifecycle(state="dormant", salience=0.3),
            )
        }
    )
    out = apply_tool_calls(
        bank, [_call(SAVE_KNOWLEDGE, id="K-001", tag="env", content="fresh again")], step=5
    )
    entry = out.bank.knowledge["K-001"]
    assert entry.lifecycle.state == "active"
    assert entry.lifecycle.salience >= 0.5


def test_delete_can_remove_an_archived_entry() -> None:
    bank = MemoryBank(
        archive={
            "K-001": MemoryEntry(
                id="K-001", kind="knowledge", content="old", created_step=1, updated_step=1
            )
        }
    )
    out = apply_tool_calls(bank, [_call(DELETE, id="K-001")], step=2)
    assert out.bank.archive == {}
    assert out.applied[0].effect == "deleted"
