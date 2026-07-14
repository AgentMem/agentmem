"""The MCP server's read-only memory access (recap / search / bank), offline."""

from __future__ import annotations

from pathlib import Path

from agentmem import mcp
from agentmem.schemas import MemoryBank, MemoryEntry
from agentmem.store import SqliteStore, open_store


def _entry(id_: str, content: str, tag: str = "task") -> MemoryEntry:
    return MemoryEntry(id=id_, kind="knowledge", tag=tag, content=content, created_step=1, updated_step=1)


def _seed_project(state_dir: Path, *entries: MemoryEntry) -> None:
    store = SqliteStore(f"{state_dir}/project.db")
    store.save_bank("project", "project memory", MemoryBank(knowledge={e.id: e for e in entries}))
    store.close()


def _seed_session(state_dir: Path, session_id: str, *entries: MemoryEntry) -> None:
    store = open_store("json", str(state_dir))
    store.save_bank(session_id, "fix", MemoryBank(knowledge={e.id: e for e in entries}))
    store.close()


def test_recap_is_empty_without_memory(tmp_path: Path) -> None:
    assert "No memory" in mcp.recap(str(tmp_path))


def test_recap_surfaces_the_project_bank(tmp_path: Path) -> None:
    _seed_project(tmp_path, _entry("PK-001", "keep the public API stable"))
    out = mcp.recap(str(tmp_path))
    assert "PK-001" in out and "public API" in out


def test_search_matches_across_banks(tmp_path: Path) -> None:
    _seed_project(tmp_path, _entry("PK-001", "cache keys must include the schema version"))
    _seed_session(tmp_path, "s1", _entry("K-001", "pytest runs from the repo root"))
    assert "PK-001" in mcp.search("cache version", str(tmp_path))
    assert "K-001" in mcp.search("pytest", str(tmp_path))


def test_search_reports_no_match(tmp_path: Path) -> None:
    _seed_project(tmp_path, _entry("PK-001", "keep the public API stable"))
    assert "No memory matches" in mcp.search("kubernetes", str(tmp_path))


def test_search_needs_a_term(tmp_path: Path) -> None:
    assert mcp.search("   ", str(tmp_path)) == "Give a search term."


def test_bank_text_renders_the_project_bank(tmp_path: Path) -> None:
    _seed_project(tmp_path, _entry("PK-001", "never touch generated code", tag="policy"))
    out = mcp.bank_text(str(tmp_path))
    assert "PK-001" in out and "generated code" in out


def test_checkpoint_surfaces_a_relevant_lesson(tmp_path: Path) -> None:
    _seed_project(
        tmp_path, _entry("PK-001", "the DEFAULT_TTL in config.py is the real fix", tag="other")
    )
    out = mcp.checkpoint(str(tmp_path), context="editing config.py for the token expiry test")
    assert "PK-001" in out and "DEFAULT_TTL" in out


def test_checkpoint_stays_silent_when_nothing_relevant(tmp_path: Path) -> None:
    _seed_project(tmp_path, _entry("PK-001", "prefer ruff over flake8 for linting", tag="other"))
    out = mcp.checkpoint(str(tmp_path), context="deploying the kubernetes cluster")
    assert "Nothing in memory" in out


def test_checkpoint_always_surfaces_policy_rules(tmp_path: Path) -> None:
    _seed_project(tmp_path, _entry("PK-001", "never touch the generated protobuf files", tag="policy"))
    out = mcp.checkpoint(str(tmp_path), context="working on the frontend styles")
    assert "PK-001" in out  # a policy rule applies even without keyword overlap


def test_checkpoint_is_silent_on_an_empty_bank(tmp_path: Path) -> None:
    assert "Nothing in memory" in mcp.checkpoint(str(tmp_path), context="anything")
