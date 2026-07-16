"""The waste metric, on hand-built command logs."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "repeat"))

from run_repeat import waste  # noqa: E402

WALL_RE = r"PytestRemovedIn10Warning|error during collection"
GREEN_RE = r"\d+ passed"
WALL = "E pytest.PytestRemovedIn10Warning\n!!! Interrupted: 1 error during collection !!!"
GREEN = "590 passed, 21 skipped in 0.6s"


def call(command: str, output: str, code: int = 0) -> dict:
    return {"command": command, "output": output, "code": code}


def test_a_clean_session_reports_no_wall() -> None:
    w = waste([call("pytest -q", GREEN)], WALL_RE, GREEN_RE)
    assert not w["wall_hit"] and w["wall_hits"] == 0
    assert w["turns_wall_to_green"] is None


def test_straight_recovery_is_three_turns() -> None:
    calls = [
        call("python -m pytest tests/ -q", WALL, 1),
        call("sed -i 's/chain(/list(chain(/' tests/test_basic.py", ""),
        call("python -m pytest tests/ -q", GREEN),
    ]
    w = waste(calls, WALL_RE, GREEN_RE)
    assert w["wall_hits"] == 1
    assert w["recovered"] and w["turns_wall_to_green"] == 3


def test_every_wall_encounter_is_counted_not_just_the_first() -> None:
    calls = [
        call("python -m pytest tests/ -q", WALL, 1),
        call("pip install 'pytest==7.4.0'", "resolution impossible", 1),
        call("python -m pytest tests/ -q", WALL, 1),
        call("sed -i 's/x/y/' tests/test_basic.py", ""),
        call("python -m pytest tests/ -q", WALL, 1),
        call("sed -i 's/chain(/list(chain(/' tests/test_basic.py", ""),
        call("python -m pytest tests/ -q", GREEN),
    ]
    w = waste(calls, WALL_RE, GREEN_RE)
    assert w["wall_hits"] == 3, "each rediscovery of the same wall costs a turn"
    assert w["turns_wall_to_green"] == 7


def test_a_wall_never_cleared_reports_none_not_a_number() -> None:
    calls = [call("python -m pytest tests/ -q", WALL, 1)] * 4
    w = waste(calls, WALL_RE, GREEN_RE)
    assert w["wall_hit"] and w["wall_hits"] == 4
    assert not w["recovered"] and w["turns_wall_to_green"] is None


def test_a_suite_that_still_has_failures_is_not_green() -> None:
    """The attrs shape: the wall is failing tests, not a collection error, so a
    summary line saying "2 failed, 1316 passed" contains the word passed and must
    not read as recovery."""
    dirty = "2 failed, 1316 passed, 8 skipped in 5.48s"
    clean = "1318 passed, 8 skipped in 5.31s"
    attrs_wall, attrs_green = r"DID NOT WARN|^\d+ failed|, \d+ failed", r"^\d+ passed"
    w = waste([call("pytest -q", dirty, 1), call("pytest -q", clean)], attrs_wall, attrs_green)
    assert w["wall_hits"] == 1 and w["recovered"] and w["turns_wall_to_green"] == 2

    stuck = waste([call("pytest -q", dirty, 1)] * 3, attrs_wall, attrs_green)
    assert stuck["wall_hits"] == 3 and not stuck["recovered"]


def test_green_before_the_wall_does_not_count_as_recovery() -> None:
    """The suite passing on some unrelated file earlier is not getting past the wall."""
    calls = [
        call("python -m pytest tests/test_one.py -q", GREEN),
        call("python -m pytest tests/ -q", WALL, 1),
    ]
    w = waste(calls, WALL_RE, GREEN_RE)
    assert w["wall_hit"] and not w["recovered"]
