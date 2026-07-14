"""Tests for the Claude Code payload-translation helpers."""

from __future__ import annotations

from agentmem.integrations import claude_code as cc
from agentmem.schemas import MemoryBank, MemoryEntry


def test_project_key_is_stable_readable_and_unique() -> None:
    key = cc.project_key("/Users/me/work/my-repo")
    assert key.startswith("my-repo-")
    assert cc.project_key("/Users/me/work/my-repo") == key  # stable
    assert cc.project_key("/Users/me/work/other") != key  # differs by dir


def test_events_from_bash_tool_use() -> None:
    events = cc.events_from_tool_use(
        "Bash", {"command": "pytest -q"}, {"stdout": "1 failed"}, ok=False
    )
    assert events[0].kind == "tool_call"
    assert events[0].text == "pytest -q"
    assert events[1].kind == "tool_result"
    assert events[1].ok is False
    assert "1 failed" in events[1].text


def test_events_prefer_command_then_path() -> None:
    events = cc.events_from_tool_use("Read", {"file_path": "src/app.py"}, {"content": "..."})
    assert events[0].text == "src/app.py"


def test_response_indicates_error() -> None:
    assert cc.response_indicates_error({"exit_code": 1}) is True
    assert cc.response_indicates_error({"error": "boom"}) is True
    assert cc.response_indicates_error({"is_error": True}) is True
    assert cc.response_indicates_error({"exit_code": 0, "stdout": "ok"}) is False
    assert cc.response_indicates_error("just a string") is False


def test_bank_digest_empty_is_none() -> None:
    assert cc.bank_digest(MemoryBank()) is None


def test_bank_digest_lists_entries_capped() -> None:
    bank = MemoryBank()
    for i in range(1, 5):
        bank.knowledge[f"K-00{i}"] = MemoryEntry(
            id=f"K-00{i}", kind="knowledge", content=f"fact {i}", created_step=i, updated_step=i
        )
    digest = cc.bank_digest(bank, max_items=2)
    assert digest is not None
    assert "(K-001) fact 1" in digest
    assert digest.count("\n- ") == 2  # capped at max_items


def test_bank_digest_lists_project_memory_before_session_memory() -> None:
    session = MemoryBank(
        knowledge={
            "K-001": MemoryEntry(
                id="K-001", kind="knowledge", content="session fact", created_step=1, updated_step=1
            )
        }
    )
    project = MemoryBank(
        knowledge={
            "PK-001": MemoryEntry(
                id="PK-001",
                kind="knowledge",
                content="project rule",
                created_step=1,
                updated_step=1,
            )
        }
    )
    digest = cc.bank_digest(session, project=project)
    assert digest is not None
    assert digest.index("PK-001") < digest.index("K-001")


def test_bank_digest_not_none_with_only_project_memory() -> None:
    project = MemoryBank(
        knowledge={
            "PK-001": MemoryEntry(
                id="PK-001", kind="knowledge", content="rule", created_step=1, updated_step=1
            )
        }
    )
    digest = cc.bank_digest(MemoryBank(), project=project)
    assert digest is not None
    assert "PK-001" in digest


def test_hook_output_shape() -> None:
    assert cc.hook_output("UserPromptSubmit", None) == {}
    out = cc.hook_output("UserPromptSubmit", "remember X")
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert out["hookSpecificOutput"]["additionalContext"] == "remember X"


def test_bank_digest_prefers_salience_over_insertion_order() -> None:
    # A digest capped at N should drop the faded tail, not the newest lessons.
    bank = MemoryBank()
    for i in range(1, 9):
        entry = MemoryEntry(
            id=f"K-00{i}", kind="knowledge", content=f"fact {i}", created_step=i, updated_step=i
        )
        entry.lifecycle.salience = i / 10  # later entries matter more here
        bank.knowledge[entry.id] = entry

    digest = cc.bank_digest(bank, max_items=2)

    assert digest is not None
    assert "fact 8" in digest and "fact 7" in digest
    assert "fact 1" not in digest
