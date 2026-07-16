"""The recall metric, on hand-built walls, banks, and reminders."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "repeat"))

from recall import recall_at_wall, signature  # noqa: E402

WALL_RE = r"PytestRemovedIn10Warning|DID NOT WARN|^\d+ failed"
CLICK_WALL = "E pytest.PytestRemovedIn10Warning in tests/test_basic.py at parametrize"
ATTRS_WALL = "FAILED tests/test_funcs.py::TestAssoc::test_unknown - DID NOT WARN"


def _call(output: str) -> dict:
    return {"command": "python -m pytest tests/ -q", "output": output}


def _rem(text: str, snapshot: dict | None = None) -> dict:
    return {"text": text, "snapshot": snapshot or {}}


def test_no_wall_gives_no_recall() -> None:
    r = recall_at_wall([_call("590 passed")], [], "K-001: anything", WALL_RE)
    assert r["wall_hit"] is False and r["recall"] is None


def test_wall_the_bank_never_knew_is_not_counted() -> None:
    """A wall with no matching entry does not count against recall; it is out of scope."""
    r = recall_at_wall([_call(CLICK_WALL)], [], "K-001: project root is /work", WALL_RE)
    assert r["wall_hit"] and not r["bank_knew"] and r["recall"] is None


def test_bank_knew_and_a_relevant_reminder_fired_is_recall_one() -> None:
    # A realistic entry names the file, as the real P-003 does.
    bank = "P-003: tests/test_basic.py line 239 uses itertools.chain, the collection error"
    reminders = [_rem("- (P-003) reapply the list(chain(...)) fix in tests/test_basic.py")]
    r = recall_at_wall([_call(CLICK_WALL)], reminders, bank, WALL_RE)
    assert r["bank_knew"] and r["relevant_fired"] and r["recall"] == 1
    assert "test_basic.py" in r["signature"]


def test_the_attrs_seed_2_case_is_recall_zero() -> None:
    """Bank held the diagnosis, wall came back, reminder was about a chore. Recall 0."""
    bank = (
        "P-004: tests/test_funcs.py test_unknown expects a DeprecationWarning assoc "
        "does not emit. P-002: there are 25 test files, largest is test_make.py"
    )
    reminders = [_rem("- (P-007) the next step is to find the largest test file")]
    r = recall_at_wall([_call(ATTRS_WALL)], reminders, bank, WALL_RE)
    assert r["bank_knew"], "test_unknown is in the bank"
    assert not r["relevant_fired"], "the reminder was about test files, not the wall"
    assert r["recall"] == 0


def test_a_relevant_reminder_via_a_cited_snapshot_counts() -> None:
    bank = "P-004: tests/test_funcs.py test_unknown expects a DeprecationWarning"
    reminders = [
        _rem("- (P-004) reapply", {"P-004": "tests/test_funcs.py test_unknown needs the warning"})
    ]
    r = recall_at_wall([_call(ATTRS_WALL)], reminders, bank, WALL_RE)
    assert r["recall"] == 1, "the signature is in the cited snapshot, not the bullet text"


def test_signature_ignores_generic_tokens() -> None:
    sig = signature("pytest failed in tests", "pytest and tests ran, failed once")
    assert sig == set(), "pytest/tests/failed are too generic to prove relevance"
