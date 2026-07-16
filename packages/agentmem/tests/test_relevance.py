"""Relevance boost: off is the identity, on saves a relevant low-salience entry."""

from __future__ import annotations

from agentmem.relevance import order, tokens
from agentmem.schemas import EntryLifecycle, MemoryBank, MemoryEntry


def _entry(eid: str, content: str, salience: float) -> MemoryEntry:
    return MemoryEntry(
        id=eid,
        kind="procedural",
        tag="attempt",
        content=content,
        created_step=1,
        updated_step=1,
        lifecycle=EntryLifecycle(salience=salience),
    )


def test_tokens_are_code_shaped_and_specific() -> None:
    t = tokens("the failure is in tests/test_funcs.py::test_unknown via assoc()")
    assert "test_funcs.py" in t and "test_unknown" in t
    assert "the" not in t and "via" not in t


def test_order_with_no_window_is_the_identity() -> None:
    es = [_entry("P-001", "a", 0.9), _entry("P-002", "b", 0.1)]
    assert [e.id for e in order(es, "")] == ["P-001", "P-002"]


def test_order_floats_the_matching_entry() -> None:
    high = _entry("P-001", "found the largest test file", 0.9)
    low = _entry("P-002", "tests/test_funcs.py test_unknown needs a DeprecationWarning", 0.1)
    ordered = order([high, low], "FAILED tests/test_funcs.py::test_unknown DID NOT WARN")
    assert ordered[0].id == "P-002", "the relevant low-salience entry comes first"


def _bank(*entries: MemoryEntry) -> MemoryBank:
    b = MemoryBank()
    for e in entries:
        b.procedural[e.id] = e
    return b


def test_cap_drops_the_relevant_entry_without_a_window() -> None:
    """The attrs seed 2 shape: cap 1, the chore note outranks the diagnosis on salience."""
    chore = _entry("P-007", "find the largest test file to finish the ticket", 0.9)
    diag = _entry("P-004", "tests/test_funcs.py test_unknown expects a DeprecationWarning", 0.2)
    render = _bank(chore, diag).render_for_agent(cap=1)
    assert "P-007" in render and "P-004" not in render


def test_the_window_saves_it() -> None:
    chore = _entry("P-007", "find the largest test file to finish the ticket", 0.9)
    diag = _entry("P-004", "tests/test_funcs.py test_unknown expects a DeprecationWarning", 0.2)
    render = _bank(chore, diag).render_for_agent(
        cap=1, window="FAILED tests/test_funcs.py::test_unknown DID NOT WARN"
    )
    assert "P-004" in render, "the diagnosis is surfaced when the wall is on screen"


def test_an_unmatched_window_leaves_the_cap_alone() -> None:
    chore = _entry("P-007", "find the largest test file", 0.9)
    diag = _entry("P-004", "tests/test_funcs.py test_unknown warning", 0.2)
    render = _bank(chore, diag).render_for_agent(cap=1, window="git commit -m done")
    assert "P-007" in render and "P-004" not in render, "no match, no change"
