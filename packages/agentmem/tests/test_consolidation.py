"""Tests for the consolidation ladder: candidate finding (pure), decision parsing
(strict), applying decisions (replays through apply_tool_calls), and the end-to-end
LLM-calling entry point against a FakeProvider."""

from __future__ import annotations

from _fakes import FakeProvider, text_response
from agentmem.agent.consolidation import (
    apply_consolidation,
    find_fusion_candidates,
    find_merge_candidates,
    parse_consolidation,
    run_consolidation,
)
from agentmem.config import AgentMemConfig
from agentmem.schemas import MemoryBank, MemoryEntry


def _entry(id_: str, kind: str, content: str, **overrides: object) -> MemoryEntry:
    defaults: dict[str, object] = {
        "id": id_,
        "kind": kind,
        "content": content,
        "created_step": 1,
        "updated_step": 1,
    }
    defaults.update(overrides)
    return MemoryEntry(**defaults)  # type: ignore[arg-type]


# ---- find_merge_candidates -------------------------------------------------


def test_finds_a_near_duplicate_pair() -> None:
    bank = MemoryBank(
        knowledge={
            "K-001": _entry("K-001", "knowledge", "Python 3.11 venv at .venv"),
            "K-002": _entry("K-002", "knowledge", "venv lives at .venv, Python 3.11"),
        }
    )
    candidates = find_merge_candidates(bank)
    assert len(candidates) == 1
    assert {candidates[0].a.id, candidates[0].b.id} == {"K-001", "K-002"}
    assert candidates[0].similarity == 5 / 6


def test_dissimilar_entries_are_not_candidates() -> None:
    bank = MemoryBank(
        knowledge={
            "K-001": _entry("K-001", "knowledge", "Python 3.11 venv at .venv"),
            "K-002": _entry("K-002", "knowledge", "npm run build fails with OOM"),
        }
    )
    assert find_merge_candidates(bank) == []


def test_different_kind_pairs_never_match() -> None:
    bank = MemoryBank(
        knowledge={"K-001": _entry("K-001", "knowledge", "identical text here")},
        procedural={"P-001": _entry("P-001", "procedural", "identical text here")},
    )
    assert find_merge_candidates(bank) == []


def test_greedy_claim_prevents_an_entry_appearing_in_two_pairs() -> None:
    bank = MemoryBank(
        knowledge={
            "K-001": _entry("K-001", "knowledge", "same same same"),
            "K-002": _entry("K-002", "knowledge", "same same same"),
            "K-003": _entry("K-003", "knowledge", "same same same"),
        }
    )
    candidates = find_merge_candidates(bank)
    assert len(candidates) == 1  # K-003 is left unclaimed, not paired twice
    claimed = {candidates[0].a.id, candidates[0].b.id}
    assert claimed == {"K-001", "K-002"}


# ---- find_fusion_candidates -------------------------------------------------


def test_finds_a_group_sharing_a_source() -> None:
    bank = MemoryBank(
        procedural={
            "P-001": _entry("P-001", "procedural", "attempt 1", source="tests/test_api.py"),
            "P-002": _entry("P-002", "procedural", "attempt 2", source="tests/test_api.py"),
            "P-003": _entry("P-003", "procedural", "attempt 3", source="tests/test_api.py"),
        }
    )
    candidates = find_fusion_candidates(bank)
    assert len(candidates) == 1
    assert candidates[0].signature == "tests/test_api.py"
    assert {e.id for e in candidates[0].entries} == {"P-001", "P-002", "P-003"}


def test_group_below_minimum_size_is_not_a_candidate() -> None:
    bank = MemoryBank(
        procedural={
            "P-001": _entry("P-001", "procedural", "attempt 1", source="tests/test_api.py"),
            "P-002": _entry("P-002", "procedural", "attempt 2", source="tests/test_api.py"),
        }
    )
    assert find_fusion_candidates(bank) == []


def test_entries_without_a_source_are_never_grouped() -> None:
    bank = MemoryBank(
        procedural={
            f"P-00{i}": _entry(f"P-00{i}", "procedural", f"attempt {i}") for i in range(1, 4)
        }
    )
    assert find_fusion_candidates(bank) == []


# ---- parse_consolidation -----------------------------------------------------


def test_parses_merge_keep_fuse_lines() -> None:
    text = (
        "[M1] MERGE: [env] venv is Python 3.11 at .venv\n"
        "[M2] KEEP\n"
        "[F1] FUSE: [fix] retry with backoff when the upstream API rate-limits\n"
        "[F2] KEEP\n"
    )
    decisions = parse_consolidation(text)
    assert decisions["M1"].action == "merge"
    assert decisions["M1"].tag == "env"
    assert decisions["M1"].content == "venv is Python 3.11 at .venv"
    assert decisions["M2"].action == "keep"
    assert decisions["F1"].action == "fuse"
    assert decisions["F1"].tag == "fix"
    assert decisions["F2"].action == "keep"


def test_missing_tag_bracket_defaults_to_other() -> None:
    decisions = parse_consolidation("[M1] MERGE: no bracket tag here")
    assert decisions["M1"].tag == "other"
    assert decisions["M1"].content == "no bracket tag here"


def test_unmentioned_candidate_is_absent_not_defaulted() -> None:
    decisions = parse_consolidation("[M1] KEEP\n")
    assert "M2" not in decisions


def test_empty_content_after_tag_is_treated_as_absent() -> None:
    decisions = parse_consolidation("[M1] MERGE: [env]   \n")
    assert "M1" not in decisions


def test_junk_text_parses_to_no_decisions() -> None:
    assert parse_consolidation("I think we should merge some things.") == {}


# ---- apply_consolidation ------------------------------------------------------


def test_merge_keeps_the_more_established_entry_and_drops_the_other() -> None:
    bank = MemoryBank(
        knowledge={
            "K-001": _entry("K-001", "knowledge", "old", access_count=3, created_step=1),
            "K-002": _entry("K-002", "knowledge", "new", access_count=0, created_step=5),
        }
    )
    merges = find_merge_candidates(
        MemoryBank(
            knowledge={
                "K-001": _entry("K-001", "knowledge", "same text", access_count=3, created_step=1),
                "K-002": _entry("K-002", "knowledge", "same text", access_count=0, created_step=5),
            }
        )
    )
    decisions = parse_consolidation("[M1] MERGE: [env] the merged fact")
    update = apply_consolidation(bank, merges, [], decisions, step=9)

    assert list(update.bank.knowledge) == ["K-001"]  # K-001 wins: higher access_count
    assert update.bank.knowledge["K-001"].content == "the merged fact"
    assert update.bank.knowledge["K-001"].lifecycle.state == "active"  # revived by the save
    effects = {a.entry_id: a.effect for a in update.applied}
    assert effects["K-002"] == "deleted"


def test_fuse_creates_an_abstract_entry_and_demotes_sources_to_dormant() -> None:
    bank = MemoryBank(
        seq_procedural=3,
        procedural={
            f"P-00{i}": _entry(f"P-00{i}", "procedural", f"attempt {i}", source="x.py")
            for i in range(1, 4)
        },
    )
    fusions = find_fusion_candidates(bank)
    decisions = parse_consolidation("[F1] FUSE: [fix] the general rule")
    update = apply_consolidation(bank, [], fusions, decisions, step=9)

    # Sources survive, demoted, never deleted.
    for i in range(1, 4):
        entry = update.bank.procedural[f"P-00{i}"]
        assert entry.lifecycle.state == "dormant"

    new_ids = set(update.bank.procedural) - {"P-001", "P-002", "P-003"}
    assert len(new_ids) == 1
    new_entry = update.bank.procedural[new_ids.pop()]
    assert new_entry.content == "the general rule"
    assert new_entry.source == "fused:P-001,P-002,P-003"


def test_keep_decision_changes_nothing() -> None:
    bank = MemoryBank(
        knowledge={
            "K-001": _entry("K-001", "knowledge", "same text"),
            "K-002": _entry("K-002", "knowledge", "same text"),
        }
    )
    merges = find_merge_candidates(bank)
    update = apply_consolidation(
        bank, merges, [], {"M1": parse_consolidation("[M1] KEEP")["M1"]}, step=1
    )
    assert set(update.bank.knowledge) == {"K-001", "K-002"}
    assert update.applied == []


def test_absent_decision_is_treated_as_keep() -> None:
    bank = MemoryBank(
        knowledge={
            "K-001": _entry("K-001", "knowledge", "same text"),
            "K-002": _entry("K-002", "knowledge", "same text"),
        }
    )
    merges = find_merge_candidates(bank)
    update = apply_consolidation(bank, merges, [], {}, step=1)
    assert set(update.bank.knowledge) == {"K-001", "K-002"}


# ---- run_consolidation (end to end against a FakeProvider) --------------------


def test_no_candidates_skips_the_llm_call_entirely() -> None:
    bank = MemoryBank(knowledge={"K-001": _entry("K-001", "knowledge", "lonely fact")})
    provider = FakeProvider()
    result = run_consolidation(provider, AgentMemConfig(), bank, step=1)
    assert result is None
    assert provider.seen == []


def test_end_to_end_merge_via_fake_provider() -> None:
    bank = MemoryBank(
        knowledge={
            "K-001": _entry("K-001", "knowledge", "Python 3.11 venv at .venv"),
            "K-002": _entry("K-002", "knowledge", "venv lives at .venv, Python 3.11"),
        }
    )
    provider = FakeProvider(phase2=[text_response("[M1] MERGE: [env] Python 3.11, venv at .venv")])
    result = run_consolidation(provider, AgentMemConfig(), bank, step=1)

    assert result is not None
    assert len(result.bank.knowledge) == 1
    assert provider.seen == ["phase2"]  # tools=None routes through the FakeProvider's phase2 path


def test_end_to_end_malformed_reply_is_a_safe_no_op() -> None:
    bank = MemoryBank(
        knowledge={
            "K-001": _entry("K-001", "knowledge", "Python 3.11 venv at .venv"),
            "K-002": _entry("K-002", "knowledge", "venv lives at .venv, Python 3.11"),
        }
    )
    provider = FakeProvider(phase2=[text_response("not a recognizable reply")])
    result = run_consolidation(provider, AgentMemConfig(), bank, step=1)

    assert result is not None
    assert set(result.bank.knowledge) == {"K-001", "K-002"}  # nothing changed
    assert result.applied == []
