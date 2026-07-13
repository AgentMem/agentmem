"""Tests for session -> project bank promotion: eligibility (pure), decision parsing
(strict), applying promotions, and the end-to-end LLM-calling entry point."""

from __future__ import annotations

from _fakes import FakeProvider, text_response
from agentmem.agent.promotion import (
    apply_promotions,
    find_promotion_candidates,
    parse_promotion,
    promotion_eligible,
    run_promotion,
)
from agentmem.config import AgentMemConfig
from agentmem.schemas import EntryLifecycle, MemoryBank, MemoryEdge, MemoryEntry


def _entry(id_: str, kind: str = "knowledge", **lifecycle_overrides: object) -> MemoryEntry:
    defaults: dict[str, object] = {
        "state": "active",
        "reinforcement": 0.5,
        "created_session": 0,
    }
    defaults.update(lifecycle_overrides)
    return MemoryEntry(
        id=id_,
        kind=kind,
        content=f"content for {id_}",
        created_step=1,
        updated_step=1,
        lifecycle=EntryLifecycle(**defaults),  # type: ignore[arg-type]
    )


# ---- promotion_eligible / find_promotion_candidates --------------------------


def test_eligible_after_three_sessions_with_positive_reinforcement() -> None:
    bank = MemoryBank(sessions_seen=3, knowledge={"K-001": _entry("K-001")})
    assert promotion_eligible(bank.knowledge["K-001"], bank, min_sessions_lived=3) is True


def test_not_eligible_before_minimum_sessions_lived() -> None:
    bank = MemoryBank(sessions_seen=2, knowledge={"K-001": _entry("K-001")})
    assert promotion_eligible(bank.knowledge["K-001"], bank, min_sessions_lived=3) is False


def test_not_eligible_with_zero_or_negative_reinforcement() -> None:
    bank = MemoryBank(sessions_seen=5, knowledge={"K-001": _entry("K-001", reinforcement=0.0)})
    assert promotion_eligible(bank.knowledge["K-001"], bank, min_sessions_lived=3) is False


def test_not_eligible_once_already_promoted() -> None:
    bank = MemoryBank(sessions_seen=5, knowledge={"K-001": _entry("K-001", promoted_from=["s1"])})
    assert promotion_eligible(bank.knowledge["K-001"], bank, min_sessions_lived=3) is False


def test_not_eligible_when_superseded() -> None:
    bank = MemoryBank(
        sessions_seen=5,
        knowledge={"K-001": _entry("K-001"), "K-002": _entry("K-002")},
        edges=[
            MemoryEdge(src="K-002", dst="K-001", rel="supersedes", confidence=0.9, evidence_step=1)
        ],
    )
    assert promotion_eligible(bank.knowledge["K-001"], bank, min_sessions_lived=3) is False


def test_find_promotion_candidates_filters_the_whole_bank() -> None:
    bank = MemoryBank(
        sessions_seen=5,
        knowledge={"K-001": _entry("K-001"), "K-002": _entry("K-002", reinforcement=-0.1)},
    )
    candidates = find_promotion_candidates(bank, min_sessions_lived=3)
    assert [e.id for e in candidates] == ["K-001"]


# ---- parse_promotion -----------------------------------------------------------


def test_parses_rewrite_and_skip_lines() -> None:
    text = "[1] [policy] always run pytest before committing\n[2] SKIP\n"
    decisions = parse_promotion(text, count=2)
    assert decisions[1].tag == "policy"
    assert decisions[1].content == "always run pytest before committing"
    assert 2 not in decisions


def test_out_of_range_index_is_ignored() -> None:
    decisions = parse_promotion("[5] [policy] whatever", count=2)
    assert decisions == {}


def test_empty_content_is_treated_as_absent() -> None:
    decisions = parse_promotion("[1] []   \n", count=1)
    assert 1 not in decisions


# ---- apply_promotions -----------------------------------------------------------


def test_apply_promotions_creates_a_project_entry_with_pk_prefix() -> None:
    session = MemoryBank(sessions_seen=5, knowledge={"K-001": _entry("K-001")})
    project = MemoryBank(sessions_seen=5)
    candidates = [session.knowledge["K-001"]]
    decisions = {1: parse_promotion("[1] [policy] never edit generated files", count=1)[1]}

    new_session, new_project = apply_promotions(
        session, project, candidates, decisions, "s1", step=9
    )

    assert list(new_project.knowledge) == ["PK-001"]
    promoted = new_project.knowledge["PK-001"]
    assert promoted.content == "never edit generated files"
    assert promoted.tag == "policy"
    assert promoted.lifecycle.tier == "project"
    assert promoted.lifecycle.promoted_from == ["s1"]


def test_apply_promotions_marks_the_session_original_as_promoted() -> None:
    session = MemoryBank(sessions_seen=5, knowledge={"K-001": _entry("K-001")})
    project = MemoryBank(sessions_seen=5)
    candidates = [session.knowledge["K-001"]]
    decisions = {1: parse_promotion("[1] [policy] rule", count=1)[1]}

    new_session, _ = apply_promotions(session, project, candidates, decisions, "s1", step=9)
    assert new_session.knowledge["K-001"].lifecycle.promoted_from == ["s1"]
    # The original is untouched otherwise: still in the session bank, still active.
    assert new_session.knowledge["K-001"].lifecycle.state == "active"


def test_apply_promotions_does_not_mutate_its_inputs() -> None:
    session = MemoryBank(sessions_seen=5, knowledge={"K-001": _entry("K-001")})
    project = MemoryBank(sessions_seen=5)
    candidates = [session.knowledge["K-001"]]
    decisions = {1: parse_promotion("[1] [policy] rule", count=1)[1]}

    apply_promotions(session, project, candidates, decisions, "s1", step=9)
    assert session.knowledge["K-001"].lifecycle.promoted_from == []
    assert project.knowledge == {}


def test_apply_promotions_skips_a_candidate_with_no_decision() -> None:
    session = MemoryBank(sessions_seen=5, knowledge={"K-001": _entry("K-001")})
    project = MemoryBank(sessions_seen=5)
    _new_session, new_project = apply_promotions(
        session, project, [session.knowledge["K-001"]], {}, "s1", step=9
    )
    assert new_project.knowledge == {}


def test_apply_promotions_enforces_the_project_cap() -> None:
    # Project bank already has 2 active entries; the cap of 2 forces a demotion when
    # promoting a 3rd (the new one always wins: it's freshest, salience 1.0).
    project = MemoryBank(
        sessions_seen=5,
        seq_knowledge=2,
        knowledge={
            "PK-001": _entry("PK-001", state="active"),
            "PK-002": _entry("PK-002", state="active"),
        },
    )
    project.knowledge["PK-001"].lifecycle.salience = 0.1
    project.knowledge["PK-002"].lifecycle.salience = 0.9
    session = MemoryBank(sessions_seen=5, knowledge={"K-001": _entry("K-001")})
    decisions = {1: parse_promotion("[1] [policy] rule", count=1)[1]}

    _new_session, new_project = apply_promotions(
        session, project, [session.knowledge["K-001"]], decisions, "s1", step=9, project_max=2
    )
    assert new_project.knowledge["PK-001"].lifecycle.state == "dormant"  # lowest salience
    assert new_project.knowledge["PK-002"].lifecycle.state == "active"
    assert new_project.knowledge["PK-003"].lifecycle.state == "active"  # promotion always lands


# ---- run_promotion (end to end against a FakeProvider) --------------------------


def test_no_candidates_skips_the_llm_call() -> None:
    session = MemoryBank()
    project = MemoryBank()
    provider = FakeProvider()
    new_session, new_project = run_promotion(
        provider, AgentMemConfig(), session, project, "s1", step=1
    )
    assert new_session is session
    assert new_project is project
    assert provider.seen == []


def test_end_to_end_promotion_via_fake_provider() -> None:
    session = MemoryBank(sessions_seen=5, knowledge={"K-001": _entry("K-001")})
    project = MemoryBank(sessions_seen=5)
    provider = FakeProvider(phase2=[text_response("[1] [policy] never touch generated code")])

    new_session, new_project = run_promotion(
        provider, AgentMemConfig(), session, project, "s1", step=1
    )
    assert list(new_project.knowledge) == ["PK-001"]
    assert new_session.knowledge["K-001"].lifecycle.promoted_from == ["s1"]


def test_end_to_end_skip_reply_promotes_nothing() -> None:
    session = MemoryBank(sessions_seen=5, knowledge={"K-001": _entry("K-001")})
    project = MemoryBank(sessions_seen=5)
    provider = FakeProvider(phase2=[text_response("[1] SKIP")])

    _new_session, new_project = run_promotion(
        provider, AgentMemConfig(), session, project, "s1", step=1
    )
    assert new_project.knowledge == {}


# ---- CLI: `agentmem bank --tier project` ----------------------------------------


def test_cli_bank_tier_project(tmp_path, capsys) -> None:  # noqa: ANN001
    from agentmem.cli import main
    from agentmem.store import SqliteStore

    store = SqliteStore(str(tmp_path / "project.db"))
    store.save_bank(
        "project",
        "project memory",
        MemoryBank(knowledge={"PK-001": _entry("PK-001")}),
    )
    store.close()

    assert main(["bank", "--tier", "project", "--state-dir", str(tmp_path)]) == 0
    assert "PK-001" in capsys.readouterr().out


def test_cli_bank_tier_project_empty(tmp_path, capsys) -> None:  # noqa: ANN001
    from agentmem.cli import main

    assert main(["bank", "--tier", "project", "--state-dir", str(tmp_path)]) == 0
    assert "No project-tier memory yet." in capsys.readouterr().out
