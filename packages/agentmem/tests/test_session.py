"""End-to-end MemorySession tests, driven by a fake provider.

Runs with async_worker=False so each observe() finishes its memory-step inline, which
keeps the tests deterministic. The async worker path has its own test below.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
from _fakes import FakeProvider, text_response, tool_response
from agentmem import MemorySession, triggers
from agentmem.config import AgentMemConfig
from agentmem.schemas import EntryLifecycle, Event, MemoryBank, MemoryEntry
from agentmem.store import SqliteStore, open_store
from agentmem.tools import SAVE_KNOWLEDGE, SAVE_PROCEDURAL, ToolCall

_INJECT = (
    "<context_for_action>\n"
    "- (P-001) test_token_expiry failed twice on the same error; fix DEFAULT_TTL, don't retry the edit.\n"
    "</context_for_action>"
)


def _cfg(tmp_path: Path) -> AgentMemConfig:
    # max_tool_rounds=1 keeps one Phase 1 call per step, matching the fake scripts.
    return AgentMemConfig(state_dir=str(tmp_path), max_tool_rounds=1)


def _fail_turn() -> list[Event]:
    return [
        Event(kind="tool_call", tool_name="bash", text="pytest -q"),
        Event(kind="tool_result", tool_name="bash", ok=False, text="FAILED test_token_expiry"),
    ]


def _scripted_provider() -> FakeProvider:
    return FakeProvider(
        phase1=[
            tool_response(
                ToolCall(
                    name=SAVE_KNOWLEDGE,
                    args={"tag": "task", "content": "don't change api.py"},
                    block_id="t1",
                ),
                ToolCall(
                    name=SAVE_PROCEDURAL,
                    args={"tag": "attempt", "content": "pytest fails: TTL wrong"},
                    block_id="t2",
                ),
            ),
            tool_response(
                ToolCall(
                    name=SAVE_PROCEDURAL,
                    args={
                        "id": "P-001",
                        "tag": "diagnosis",
                        "content": "root cause is DEFAULT_TTL",
                    },
                    block_id="t3",
                ),
            ),
        ],
        phase2=[text_response("<no_intervention/>"), text_response(_INJECT)],
    )


def test_silent_then_intervenes(tmp_path: Path) -> None:
    provider = _scripted_provider()
    with MemorySession(
        task="fix the tests",
        config=_cfg(tmp_path),
        provider=provider,
        session_id="s1",
        trigger=triggers.default(3),
        async_worker=False,
    ) as mem:
        mem.observe(_fail_turn())  # step 1: records, stays silent
        assert mem.pending_context() is None

        mem.observe(_fail_turn())  # step 2: diagnoses, speaks up
        reminder = mem.pending_context()

    assert reminder is not None
    assert "P-001" in reminder
    assert "DEFAULT_TTL" in reminder


def test_pending_context_is_consumed_once(tmp_path: Path) -> None:
    with MemorySession(
        task="fix",
        config=_cfg(tmp_path),
        provider=_scripted_provider(),
        session_id="s1",
        async_worker=False,
    ) as mem:
        mem.observe(_fail_turn())
        mem.observe(_fail_turn())
        first = mem.pending_context()
        second = mem.pending_context()

    assert first is not None
    assert second is None  # transient: read once, then gone


def test_bank_persists_across_sessions(tmp_path: Path) -> None:
    with MemorySession(
        task="fix",
        config=_cfg(tmp_path),
        provider=_scripted_provider(),
        session_id="proj",
        async_worker=False,
    ) as mem:
        mem.observe(_fail_turn())
        mem.observe(_fail_turn())

    # A fresh store on the same dir sees the bank the run left behind.
    reloaded = open_store("json", str(tmp_path)).load_bank("proj")
    assert reloaded is not None
    assert "K-001" in reloaded.knowledge
    assert reloaded.procedural["P-001"].tag == "diagnosis"


def test_no_step_when_trigger_stays_quiet(tmp_path: Path) -> None:
    provider = FakeProvider()  # empty scripts; must never be consulted
    with MemorySession(
        task="t",
        config=_cfg(tmp_path),
        provider=provider,
        session_id="s",
        trigger=triggers.every_n(3),
        async_worker=False,
    ) as mem:
        mem.observe([Event(role="assistant", text="hello")])  # turn 1 -> first_step
        provider.seen.clear()
        mem.observe([Event(role="assistant", text="still going")])  # turn 2 -> no fire
        mem.observe([Event(role="assistant", text="and again")])  # turn 3 -> no fire

    assert provider.seen == []


def test_telemetry_written(tmp_path: Path) -> None:
    with MemorySession(
        task="fix",
        config=_cfg(tmp_path),
        provider=_scripted_provider(),
        session_id="s",
        async_worker=False,
    ) as mem:
        mem.observe(_fail_turn())
        mem.observe(_fail_turn())

    lines = (Path(tmp_path) / "telemetry.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2  # one row per step, silent ones included


def test_async_worker_flush(tmp_path: Path) -> None:
    # Same scenario through the background worker; flush() waits for it to drain.
    with MemorySession(
        task="fix",
        config=_cfg(tmp_path),
        provider=_scripted_provider(),
        session_id="a",
        async_worker=True,
    ) as mem:
        mem.observe(_fail_turn())
        mem.observe(_fail_turn())
        mem.flush()
        reminder = mem.pending_context()

    assert reminder is not None
    assert "P-001" in reminder


def test_close_bumps_sessions_seen(tmp_path: Path) -> None:
    with MemorySession(
        task="fix",
        config=_cfg(tmp_path),
        provider=FakeProvider(),
        session_id="s1",
        async_worker=False,
    ):
        pass
    reloaded = open_store("json", str(tmp_path)).load_bank("s1")
    assert reloaded is not None
    assert reloaded.sessions_seen == 1


def test_end_session_does_not_tear_down_the_session(tmp_path: Path) -> None:
    # The daemon calls this on Claude Code's SessionEnd but keeps serving the same
    # project session afterward, so it must stay usable.
    mem = MemorySession(
        task="fix",
        config=_cfg(tmp_path),
        provider=_scripted_provider(),
        session_id="s1",
        async_worker=False,
    )
    mem.observe(_fail_turn())
    mem.end_session()
    assert mem.bank.sessions_seen == 1

    mem.observe(_fail_turn())  # still usable: this diagnoses and speaks up
    reminder = mem.pending_context()
    assert reminder is not None
    mem.close()


def test_end_session_runs_on_the_worker_in_async_mode(tmp_path: Path) -> None:
    with MemorySession(
        task="fix",
        config=_cfg(tmp_path),
        provider=FakeProvider(),
        session_id="s1",
        async_worker=True,
    ) as mem:
        mem.end_session()
        mem.flush()  # end_session() is just enqueued; flush() waits for the worker
        assert mem.bank.sessions_seen == 1


def test_precompact_tick_runs_consolidation(tmp_path: Path) -> None:
    store = open_store("json", str(tmp_path))
    seeded = MemoryBank(
        knowledge={
            "K-001": MemoryEntry(
                id="K-001",
                kind="knowledge",
                content="Python 3.11 venv at .venv",
                created_step=1,
                updated_step=1,
            ),
            "K-002": MemoryEntry(
                id="K-002",
                kind="knowledge",
                content="venv lives at .venv, Python 3.11",
                created_step=1,
                updated_step=1,
            ),
        }
    )
    store.save_bank("s1", "fix", seeded)
    store.close()

    provider = FakeProvider(
        phase2=[
            text_response("<no_intervention/>"),  # the normal step's Phase 2 call
            text_response("[M1] MERGE: [env] Python 3.11, venv at .venv"),  # consolidation
        ]
    )
    with MemorySession(
        task="fix", config=_cfg(tmp_path), provider=provider, session_id="s1", async_worker=False
    ) as mem:
        mem.tick("pre_compact", consolidate=True)
        assert len(mem.bank.knowledge) == 1


def test_consolidate_false_leaves_near_duplicates_alone(tmp_path: Path) -> None:
    store = open_store("json", str(tmp_path))
    store.save_bank(
        "s1",
        "fix",
        MemoryBank(
            knowledge={
                "K-001": MemoryEntry(
                    id="K-001",
                    kind="knowledge",
                    content="Python 3.11 venv at .venv",
                    created_step=1,
                    updated_step=1,
                ),
                "K-002": MemoryEntry(
                    id="K-002",
                    kind="knowledge",
                    content="venv lives at .venv, Python 3.11",
                    created_step=1,
                    updated_step=1,
                ),
            }
        ),
    )
    store.close()

    provider = FakeProvider(phase2=[text_response("<no_intervention/>")])
    with MemorySession(
        task="fix", config=_cfg(tmp_path), provider=provider, session_id="s1", async_worker=False
    ) as mem:
        mem.tick("manual")  # consolidate defaults to False
        assert len(mem.bank.knowledge) == 2


def test_project_bank_loads_what_a_prior_session_promoted(tmp_path: Path) -> None:
    project_store = SqliteStore(str(tmp_path / "project.db"))
    project_store.save_bank(
        "project",
        "project memory",
        MemoryBank(
            knowledge={
                "PK-001": MemoryEntry(
                    id="PK-001",
                    kind="knowledge",
                    tag="policy",
                    content="never touch generated code",
                    created_step=1,
                    updated_step=1,
                    lifecycle=EntryLifecycle(tier="project"),
                )
            }
        ),
    )
    project_store.close()

    with MemorySession(
        task="fix",
        config=_cfg(tmp_path),
        provider=FakeProvider(),
        session_id="s1",
        async_worker=False,
    ) as mem:
        assert "PK-001" in mem.project_bank.knowledge


def test_close_promotes_an_eligible_entry_to_the_project_bank(tmp_path: Path) -> None:
    store = open_store("json", str(tmp_path))
    store.save_bank(
        "s1",
        "fix",
        MemoryBank(
            sessions_seen=5,
            knowledge={
                "K-001": MemoryEntry(
                    id="K-001",
                    kind="knowledge",
                    content="run pytest before committing",
                    created_step=1,
                    updated_step=1,
                    lifecycle=EntryLifecycle(reinforcement=0.5, created_session=0),
                )
            },
        ),
    )
    store.close()

    provider = FakeProvider(
        phase2=[text_response("[1] [policy] always run pytest before committing")]
    )
    with MemorySession(
        task="fix", config=_cfg(tmp_path), provider=provider, session_id="s1", async_worker=False
    ):
        pass  # nothing to observe; close() alone should promote K-001

    reloaded = SqliteStore(str(tmp_path / "project.db")).load_bank("project")
    assert reloaded is not None
    assert list(reloaded.knowledge) == ["PK-001"]
    assert reloaded.knowledge["PK-001"].content == "always run pytest before committing"


def test_phase2_can_cite_a_project_tier_entry(tmp_path: Path) -> None:
    project_store = SqliteStore(str(tmp_path / "project.db"))
    project_store.save_bank(
        "project",
        "project memory",
        MemoryBank(
            knowledge={
                "PK-001": MemoryEntry(
                    id="PK-001",
                    kind="knowledge",
                    tag="policy",
                    content="never touch generated code",
                    created_step=1,
                    updated_step=1,
                    lifecycle=EntryLifecycle(tier="project"),
                )
            }
        ),
    )
    project_store.close()

    reminder = "<context_for_action>\n- (PK-001) never touch generated code.\n</context_for_action>"
    provider = FakeProvider(phase1=[tool_response()], phase2=[text_response(reminder)])
    with MemorySession(
        task="fix", config=_cfg(tmp_path), provider=provider, session_id="s1", async_worker=False
    ) as mem:
        mem.tick("manual")
        pending = mem.pending_context()

    assert pending is not None
    assert "PK-001" in pending
    # The injector found and bumped the project-tier entry, not just parsed its id.
    assert mem.project_bank.knowledge["PK-001"].access_count == 1


def _reinforcement_provider(evaluator_json: str) -> FakeProvider:
    return FakeProvider(
        phase1=[
            tool_response(
                ToolCall(
                    name=SAVE_KNOWLEDGE,
                    args={"tag": "task", "content": "keep the public API stable"},
                    block_id="k",
                )
            ),
            tool_response(),  # step 2 makes no edits
        ],
        phase2=[
            text_response("<no_intervention/>"),  # step 1: silent
            text_response(
                "<context_for_action>\n- (K-001) keep the API stable\n</context_for_action>"
            ),
            text_response(evaluator_json),  # the Outcome Evaluator at SessionEnd
        ],
    )


def test_useful_reminder_reinforces_the_cited_entry(tmp_path: Path) -> None:
    config = AgentMemConfig(state_dir=str(tmp_path), max_tool_rounds=1, advantage_enabled=True)
    mem = MemorySession(
        task="fix",
        config=config,
        provider=_reinforcement_provider('[{"step":1,"reward":0.1},{"step":2,"reward":0.8}]'),
        session_id="s1",
        async_worker=False,
    )
    mem.observe(_fail_turn())  # step 1: saves K-001, stays silent
    mem.observe(_fail_turn())  # step 2: injects, citing K-001
    mem.close(task_reward=1.0)

    # Step 2's reminder cited K-001 and graded positive, so K-001 gains +0.3.
    assert mem.bank.knowledge["K-001"].lifecycle.reinforcement == pytest.approx(0.3)


def test_useless_reminder_debits_the_cited_entry(tmp_path: Path) -> None:
    config = AgentMemConfig(state_dir=str(tmp_path), max_tool_rounds=1, advantage_enabled=True)
    mem = MemorySession(
        task="fix",
        config=config,
        provider=_reinforcement_provider('[{"step":1,"reward":0.0},{"step":2,"reward":-0.5}]'),
        session_id="s1",
        async_worker=False,
    )
    mem.observe(_fail_turn())
    mem.observe(_fail_turn())
    mem.close(task_reward=-1.0)

    assert mem.bank.knowledge["K-001"].lifecycle.reinforcement == pytest.approx(-0.2)


def test_reinforcement_stays_zero_without_the_advantage_layer(tmp_path: Path) -> None:
    # Advantage off (default) means no evaluator, so reinforcement never moves.
    mem = MemorySession(
        task="fix",
        config=_cfg(tmp_path),
        provider=_reinforcement_provider("unused"),
        session_id="s1",
        async_worker=False,
    )
    mem.observe(_fail_turn())
    mem.observe(_fail_turn())
    mem.close()

    assert mem.bank.knowledge["K-001"].lifecycle.reinforcement == 0.0


class _BoomProvider:
    """A provider that always blows up, to prove failures get logged, not swallowed."""

    model = "boom"

    def complete(self, **kwargs: object) -> object:
        raise RuntimeError("provider exploded")


def _near_duplicate_bank() -> MemoryBank:
    return MemoryBank(
        knowledge={
            "K-001": MemoryEntry(
                id="K-001",
                kind="knowledge",
                content="Python 3.11 venv at .venv",
                created_step=1,
                updated_step=1,
            ),
            "K-002": MemoryEntry(
                id="K-002",
                kind="knowledge",
                content="venv lives at .venv, Python 3.11",
                created_step=1,
                updated_step=1,
            ),
        }
    )


def test_consolidation_failure_is_logged_not_swallowed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    store = open_store("json", str(tmp_path))
    store.save_bank("s1", "fix", _near_duplicate_bank())  # forces a merge candidate
    store.close()

    mem = MemorySession(
        task="fix",
        config=_cfg(tmp_path),
        provider=_BoomProvider(),
        session_id="s1",
        async_worker=False,
    )
    with caplog.at_level(logging.WARNING, logger="agentmem"):
        mem.end_session()  # runs consolidation, which calls the exploding provider
    mem.close()

    assert any("consolidation skipped" in r.getMessage() for r in caplog.records)


def test_async_worker_logs_a_failed_step(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    mem = MemorySession(
        task="fix",
        config=_cfg(tmp_path),
        provider=_BoomProvider(),
        session_id="s1",
        trigger=triggers.every_n(1),
        async_worker=True,
    )
    with caplog.at_level(logging.ERROR, logger="agentmem"):
        mem.observe([Event(role="assistant", text="do a thing")])  # fires a step on the worker
        mem.flush()
    mem.close()

    assert any("memory-step failed" in r.getMessage() for r in caplog.records)
