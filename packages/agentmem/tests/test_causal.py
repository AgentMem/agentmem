"""Causal edges: the memory_link reducer and edge rendering."""

from __future__ import annotations

from agentmem.agent.phase2 import Bullet
from agentmem.agent.prompts import phase1_system, phase2_system
from agentmem.bank import BankLimits, apply_tool_calls
from agentmem.config import AgentMemConfig
from agentmem.injector import Injector
from agentmem.schemas import MemoryBank
from agentmem.tools import DELETE, LINK, SAVE_KNOWLEDGE, SAVE_PROCEDURAL, ToolCall


def _call(name: str, **args: object) -> ToolCall:
    return ToolCall(name=name, args=args)


def _seed(n_knowledge: int = 1, n_procedural: int = 1) -> MemoryBank:
    calls = [_call(SAVE_KNOWLEDGE, tag="env", content=f"fact {i}") for i in range(n_knowledge)]
    calls += [_call(SAVE_PROCEDURAL, tag="bug", content=f"bug {i}") for i in range(n_procedural)]
    return apply_tool_calls(MemoryBank(), calls, step=1).bank


def _link(**args: object) -> ToolCall:
    base = {
        "src": "P-001",
        "dst": "K-001",
        "rel": "caused_by",
        "confidence": 0.8,
        "evidence_step": 3,
    }
    return _call(LINK, **{**base, **args})


def test_link_two_entries() -> None:
    out = apply_tool_calls(_seed(), [_link()], step=2)
    assert out.applied[0].effect == "linked"
    assert len(out.bank.edges) == 1
    edge = out.bank.edges[0]
    assert (edge.src, edge.dst, edge.rel) == ("P-001", "K-001", "caused_by")
    assert edge.confidence == 0.8


def test_self_loop_rejected() -> None:
    out = apply_tool_calls(_seed(), [_link(src="K-001", dst="K-001")], step=2)
    assert out.applied[0].effect == "rejected"
    assert out.applied[0].note == "self-loop"
    assert out.bank.edges == []


def test_missing_endpoint_rejected() -> None:
    out = apply_tool_calls(_seed(), [_link(dst="K-999")], step=2)
    assert out.applied[0].note == "endpoint missing"


def test_unknown_relation_rejected() -> None:
    out = apply_tool_calls(_seed(), [_link(rel="because")], step=2)
    assert out.applied[0].note == "unknown relation"


def test_duplicate_rejected() -> None:
    out = apply_tool_calls(_seed(), [_link(), _link()], step=2)
    assert out.applied[0].effect == "linked"
    assert out.applied[1].note == "duplicate edge"
    assert len(out.bank.edges) == 1


def test_missing_evidence_step_rejected() -> None:
    out = apply_tool_calls(
        _seed(), [_call(LINK, src="P-001", dst="K-001", rel="caused_by", confidence=0.5)], step=2
    )
    assert out.applied[0].note == "missing evidence_step"


def test_confidence_is_clamped() -> None:
    out = apply_tool_calls(_seed(), [_link(confidence=1.7)], step=2)
    assert out.bank.edges[0].confidence == 1.0


def test_per_source_budget() -> None:
    limits = BankLimits(max_edges_per_src=1)
    bank = _seed(n_knowledge=2)  # K-001, K-002, P-001
    out = apply_tool_calls(
        bank,
        [_link(dst="K-001"), _link(dst="K-002")],
        step=2,
        limits=limits,
    )
    assert out.applied[0].effect == "linked"
    assert out.applied[1].note == "too many links from this entry"


def test_total_edge_budget() -> None:
    limits = BankLimits(max_edges=1, max_edges_per_src=5)
    bank = _seed(n_knowledge=2, n_procedural=2)  # K-001/2, P-001/2
    out = apply_tool_calls(
        bank,
        [_link(src="P-001", dst="K-001"), _link(src="P-002", dst="K-002")],
        step=2,
        limits=limits,
    )
    assert out.applied[0].effect == "linked"
    assert out.applied[1].note == "edge budget full"


def test_remove_edge() -> None:
    linked = apply_tool_calls(_seed(), [_link()], step=2).bank
    out = apply_tool_calls(linked, [_link(remove=True)], step=3)
    assert out.applied[0].effect == "unlinked"
    assert out.bank.edges == []

    missing = apply_tool_calls(_seed(), [_link(remove=True)], step=2)
    assert missing.applied[0].note == "no such edge"


def test_delete_cascades_edges() -> None:
    linked = apply_tool_calls(_seed(), [_link()], step=2).bank
    out = apply_tool_calls(linked, [_call(DELETE, id="K-001")], step=3)
    assert "K-001" not in out.bank.knowledge
    assert out.bank.edges == []  # the edge to K-001 went with it


def test_edges_survive_json_round_trip() -> None:
    bank = apply_tool_calls(_seed(), [_link()], step=2).bank
    assert MemoryBank.model_validate_json(bank.model_dump_json()) == bank


def test_render_shows_causal_links() -> None:
    bank = apply_tool_calls(_seed(), [_link()], step=2).bank
    text = bank.render_for_agent()
    assert "CAUSAL LINKS:" in text
    assert "P-001 --caused_by--> K-001" in text


def _linked_bank(confidence: float = 0.8) -> MemoryBank:
    seed = apply_tool_calls(
        MemoryBank(),
        [
            _call(
                SAVE_KNOWLEDGE, tag="env", content="fixtures derive from schema; run make generate"
            ),
            _call(SAVE_PROCEDURAL, tag="bug", content="KeyError display_name in serializer"),
        ],
        step=1,
    ).bank
    return apply_tool_calls(seed, [_link(confidence=confidence)], step=2).bank


def _bullet() -> Bullet:
    return Bullet(line="(P-001) serializer raises KeyError", cited_ids=["P-001"])


def test_causal_tail_appears_in_reminder() -> None:
    inj = Injector(AgentMemConfig(causal_enabled=True, causal_min_confidence=0.7))
    out = inj.build([_bullet()], _linked_bank(), step=3)
    assert out is not None
    assert "caused_by K-001" in out.text  # the chain rides along on the bullet


def test_causal_tail_off_when_disabled() -> None:
    inj = Injector(AgentMemConfig(causal_enabled=False))
    out = inj.build([_bullet()], _linked_bank(), step=3)
    assert out is not None
    assert "caused_by" not in out.text


def test_low_confidence_edge_not_rendered() -> None:
    inj = Injector(AgentMemConfig(causal_enabled=True, causal_min_confidence=0.7))
    out = inj.build([_bullet()], _linked_bank(confidence=0.4), step=3)
    assert out is not None
    assert "caused_by" not in out.text


def test_causal_prompt_addenda_are_conditional() -> None:
    assert "memory_link" in phase1_system(True)
    assert "memory_link" not in phase1_system(False)
    assert "CAUSAL LINKS" in phase2_system(True)
    assert "CAUSAL LINKS" not in phase2_system(False)


def test_bank_digest_includes_strong_edges() -> None:
    from agentmem.integrations.claude_code import bank_digest

    digest = bank_digest(_linked_bank(confidence=0.9))
    assert digest is not None
    assert "P-001 --caused_by--> K-001" in digest


def test_cli_bank_graph(tmp_path, capsys) -> None:  # noqa: ANN001
    from agentmem.cli import main
    from agentmem.store import open_store

    store = open_store("json", str(tmp_path))
    store.save_bank("s", "task", _linked_bank())
    store.close()

    assert main(["bank", "--session", "s", "--graph", "--state-dir", str(tmp_path)]) == 0
    assert "P-001 --caused_by--> K-001" in capsys.readouterr().out


def test_causal_chain_reaches_the_reminder(tmp_path) -> None:  # noqa: ANN001
    """End to end: the memory agent links two entries, and a later reminder carries
    the cause/fix chain through a real MemorySession."""
    from _fakes import FakeProvider, text_response, tool_response
    from agentmem import MemorySession
    from agentmem.schemas import Event

    provider = FakeProvider(
        phase1=[
            tool_response(
                ToolCall(
                    name=SAVE_KNOWLEDGE,
                    block_id="k",
                    args={
                        "tag": "env",
                        "content": "fixtures derive from schema; run make generate",
                    },
                ),
                ToolCall(
                    name=SAVE_PROCEDURAL,
                    block_id="p",
                    args={"tag": "bug", "content": "serializer raises KeyError display_name"},
                ),
            ),
            tool_response(
                ToolCall(
                    name=LINK,
                    block_id="l",
                    args={
                        "src": "P-001",
                        "dst": "K-001",
                        "rel": "caused_by",
                        "confidence": 0.9,
                        "evidence_step": 2,
                    },
                ),
            ),
        ],
        phase2=[
            text_response("<no_intervention/>"),
            text_response(
                "<context_for_action>\n- (P-001) serializer raises KeyError\n</context_for_action>"
            ),
        ],
    )
    config = AgentMemConfig(state_dir=str(tmp_path), max_tool_rounds=1, causal_enabled=True)
    fail = [Event(kind="tool_result", tool_name="bash", ok=False, text="KeyError: display_name")]

    with MemorySession(
        task="fix the api", config=config, provider=provider, session_id="c", async_worker=False
    ) as mem:
        mem.observe(fail)  # step 1: banks K-001 + P-001, stays silent
        assert mem.pending_context() is None
        mem.observe(fail)  # step 2: links P-001 caused_by K-001, then speaks
        reminder = mem.pending_context()

    assert reminder is not None
    assert "P-001" in reminder
    assert "caused_by K-001" in reminder  # the chain rode along on the bullet


def test_link_revives_and_reinforces_both_endpoints() -> None:
    # The long-run failure shape: a lesson went dormant, then a later entry linked to
    # it. The link is evidence it still matters, so it comes back and earns credit.
    bank = _seed()
    bank.sessions_seen = 16
    for eid, rf in (("P-001", 0.9), ("K-001", 0.0)):
        entry = bank.entry(eid)
        assert entry is not None
        entry.lifecycle.state = "dormant"
        entry.lifecycle.salience = 0.22
        entry.lifecycle.last_touched_session = 4
        entry.lifecycle.reinforcement = rf

    out = apply_tool_calls(bank, [_link()], step=2)

    for eid in ("P-001", "K-001"):
        entry = out.bank.entry(eid)
        assert entry is not None
        lc = entry.lifecycle
        assert lc.state == "active"
        assert lc.salience >= 0.5
        assert lc.last_touched_session == 16
    p = out.bank.entry("P-001")
    k = out.bank.entry("K-001")
    assert p is not None and k is not None
    assert p.lifecycle.reinforcement == 1.0  # capped, not 1.2
    assert k.lifecycle.reinforcement == 0.3


def test_link_remove_leaves_lifecycles_alone() -> None:
    linked = apply_tool_calls(_seed(), [_link()], step=2).bank
    for eid in ("P-001", "K-001"):
        entry = linked.entry(eid)
        assert entry is not None
        entry.lifecycle.state = "dormant"
        entry.lifecycle.reinforcement = 0.0

    out = apply_tool_calls(linked, [_link(remove=True)], step=3)

    assert out.applied[0].effect == "unlinked"
    for eid in ("P-001", "K-001"):
        entry = out.bank.entry(eid)
        assert entry is not None
        assert entry.lifecycle.state == "dormant"
        assert entry.lifecycle.reinforcement == 0.0


def test_rejected_link_touches_nothing() -> None:
    bank = _seed()
    p = bank.entry("P-001")
    assert p is not None
    p.lifecycle.state = "dormant"
    p.lifecycle.salience = 0.22

    out = apply_tool_calls(bank, [_link(dst="K-999")], step=2)  # endpoint missing

    assert out.applied[0].effect == "rejected"
    p2 = out.bank.entry("P-001")
    assert p2 is not None
    assert p2.lifecycle.state == "dormant"
    assert p2.lifecycle.reinforcement == 0.0
