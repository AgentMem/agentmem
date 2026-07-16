"""The compaction scorer, on transcripts built with the mock's own schema builders."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "compaction"))

import score  # noqa: E402
from mock_claude import GREEN, PYTEST, WALL, Transcript  # noqa: E402

WALL_RE = r"PytestRemovedIn10Warning"
GREEN_RE = r"\d+ passed"


def _t(tmp_path: Path) -> Transcript:
    return Transcript(tmp_path / "t.jsonl", "test")


def test_no_boundary_is_an_error_not_a_zero(tmp_path: Path) -> None:
    t = _t(tmp_path)
    t.tool("Bash", PYTEST, GREEN)
    with pytest.raises(ValueError, match="compact never happened"):
        score.post_compact_metrics(score.load(t.path), WALL_RE, GREEN_RE)


def test_verify_after_fix_is_not_a_repeat(tmp_path: Path) -> None:
    t = _t(tmp_path)
    t.compact()
    t.tool("Bash", PYTEST, WALL, is_error=True)
    t.tool("Edit", "fix tests/test_basic.py", "ok")
    t.tool("Bash", PYTEST, GREEN)
    m = score.post_compact_metrics(score.load(t.path), WALL_RE, GREEN_RE)
    assert m["repeats_of_known_failures"] == 0
    assert m["recovered"] and m["calls_wall_to_green"] == 3


def test_rerun_without_an_edit_is_a_repeat(tmp_path: Path) -> None:
    t = _t(tmp_path)
    t.compact()
    t.tool("Bash", PYTEST, WALL, is_error=True)
    t.tool("Bash", PYTEST, WALL, is_error=True)
    t.tool("Bash", "grep -rn parametrize tests/", "tests/test_basic.py:239")
    t.tool("Bash", PYTEST, WALL, is_error=True)
    t.tool("Edit", "fix tests/test_basic.py", "ok")
    t.tool("Bash", PYTEST, GREEN)
    m = score.post_compact_metrics(score.load(t.path), WALL_RE, GREEN_RE)
    assert m["repeats_of_known_failures"] == 2, "a grep between reruns changes nothing"


def test_only_post_compact_work_is_counted(tmp_path: Path) -> None:
    t = _t(tmp_path)
    t.tool("Bash", PYTEST, WALL, is_error=True)
    t.tool("Bash", PYTEST, WALL, is_error=True)
    t.compact()
    t.tool("Bash", PYTEST, WALL, is_error=True)
    t.tool("Edit", "fix", "ok")
    t.tool("Bash", PYTEST, GREEN)
    m = score.post_compact_metrics(score.load(t.path), WALL_RE, GREEN_RE)
    assert m["repeats_of_known_failures"] == 0
    assert m["post_compact_tool_calls"] == 3


def test_unrecovered_wall_reports_none_not_a_number(tmp_path: Path) -> None:
    t = _t(tmp_path)
    t.compact()
    t.tool("Bash", PYTEST, WALL, is_error=True)
    m = score.post_compact_metrics(score.load(t.path), WALL_RE, GREEN_RE)
    assert m["wall_reencountered"] and not m["recovered"]
    assert m["calls_wall_to_green"] is None


def test_probe_text_is_the_last_prose_not_the_last_tool_turn(tmp_path: Path) -> None:
    t = _t(tmp_path)
    t.assistant_text("the actual probe answer about tests/test_basic.py")
    t.tool("Bash", "true", "ok")
    entries = score.load(t.path)
    assert "test_basic.py" in score.last_assistant_text(entries)
