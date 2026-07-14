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
