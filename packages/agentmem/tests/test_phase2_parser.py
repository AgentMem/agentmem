"""Tests for the Phase 2 parser."""

from __future__ import annotations

from agentmem.agent.phase2 import parse_phase2


def test_no_intervention_is_silence() -> None:
    assert parse_phase2("<no_intervention/>") == []
    assert parse_phase2("<no_intervention />") == []
    assert parse_phase2("  <no_intervention/>  \n") == []


def test_single_grounded_bullet() -> None:
    text = "<context_for_action>\n- (K-004) do not touch the public API\n</context_for_action>"
    bullets = parse_phase2(text)
    assert len(bullets) == 1
    assert bullets[0].cited_ids == ["K-004"]
    assert "public API" in bullets[0].line


def test_multiple_bullets_and_ids() -> None:
    text = (
        "<context_for_action>\n"
        "- (K-001) requirement: python 3.11\n"
        "- (P-011) pip install failed twice; use --no-cache-dir\n"
        "</context_for_action>"
    )
    bullets = parse_phase2(text)
    assert [b.cited_ids for b in bullets] == [["K-001"], ["P-011"]]


def test_ungrounded_bullets_are_dropped() -> None:
    # A bullet with no id is ungrounded and must not survive.
    text = "<context_for_action>\n- just be careful out there\n- (P-003) real one\n</context_for_action>"
    bullets = parse_phase2(text)
    assert len(bullets) == 1
    assert bullets[0].cited_ids == ["P-003"]


def test_empty_context_block_is_silence() -> None:
    assert parse_phase2("<context_for_action>\n\n</context_for_action>") == []


def test_garbage_is_silence() -> None:
    assert parse_phase2("Sure! Here are some thoughts about your code...") == []
    assert parse_phase2("") == []


def test_tolerates_star_bullets_and_bare_lines() -> None:
    text = "<context_for_action>\n* (K-002) star bullet\n(P-009) bare line\n</context_for_action>"
    bullets = parse_phase2(text)
    assert {b.cited_ids[0] for b in bullets} == {"K-002", "P-009"}


def test_case_insensitive_tags() -> None:
    assert parse_phase2("<NO_INTERVENTION/>") == []
    assert len(parse_phase2("<CONTEXT_FOR_ACTION>\n- (K-1) x\n</CONTEXT_FOR_ACTION>")) == 1
