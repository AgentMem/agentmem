"""MCP server: read-only memory for any MCP host (Cursor, Copilot, Codex, Gemini CLI,
Continue, Windsurf).

An MCP host can only ask for memory on demand, it can't be handed a reminder mid-turn,
so this exposes three questions an agent can ask about the project it's working in: a
recap, a keyword search, and the full project bank. They read the on-disk banks and
never call a model.

The memory-access functions here are plain and testable; the FastMCP wrapping in
`build_server()` / `main()` is a thin shell imported lazily, so `import agentmem.mcp`
doesn't require the `mcp` package until you actually run the server.
"""

from __future__ import annotations

from typing import Any

from .config import AgentMemConfig
from .integrations.claude_code import bank_digest
from .schemas import MemoryBank
from .store import SqliteStore, open_store

_MAX_HITS = 20


def _project_bank(config: AgentMemConfig) -> MemoryBank:
    store = SqliteStore(f"{config.state_dir}/project.db")
    try:
        return store.load_bank("project") or MemoryBank()
    finally:
        store.close()


def _latest_session_bank(config: AgentMemConfig) -> MemoryBank:
    store = open_store(config.store, config.state_dir)
    try:
        sessions = sorted(store.list_sessions(), key=lambda s: s.updated_at, reverse=True)
        if not sessions:
            return MemoryBank()
        return store.load_bank(sessions[0].session_id) or MemoryBank()
    finally:
        store.close()


def _all_banks(config: AgentMemConfig) -> list[MemoryBank]:
    banks = [_project_bank(config)]
    store = open_store(config.store, config.state_dir)
    try:
        for info in store.list_sessions():
            bank = store.load_bank(info.session_id)
            if bank is not None:
                banks.append(bank)
    finally:
        store.close()
    return banks


def recap(state_dir: str = ".agentmem") -> str:
    """A short digest of what AgentMem remembers about this project: the durable
    project bank first, then the most recent session's bank."""
    config = AgentMemConfig(state_dir=state_dir)
    digest = bank_digest(_latest_session_bank(config), project=_project_bank(config))
    return digest or "No memory stored for this project yet."


def search(query: str, state_dir: str = ".agentmem") -> str:
    """Keyword search across every stored bank. Returns matching entries, id-cited."""
    config = AgentMemConfig(state_dir=state_dir)
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return "Give a search term."

    hits: list[str] = []
    seen: set[str] = set()
    for bank in _all_banks(config):
        for entry in bank.all_entries():
            if entry.id in seen:
                continue
            if any(t in entry.content.lower() for t in terms):
                seen.add(entry.id)
                hits.append(f"({entry.id}) [{entry.tag}] {entry.content}")
    if not hits:
        return f"No memory matches {query!r}."
    return "\n".join(hits[:_MAX_HITS])


def bank_text(state_dir: str = ".agentmem") -> str:
    """The full durable project bank, human-readable."""
    project = _project_bank(AgentMemConfig(state_dir=state_dir))
    if project.is_empty():
        return "No project-tier memory yet."
    return project.render_full()


# Stable handles so build_server can register the three functions above under clean tool
# names without the inner `def recap` shadowing them.
_CORE: dict[str, Any] = {"recap": recap, "search": search, "bank": bank_text}


def build_server(state_dir: str | None = None) -> Any:
    """Build the FastMCP server exposing recap / search / bank as read-only tools. The
    `mcp` SDK is imported here, so the rest of this module works without it installed."""
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - only without the mcp SDK installed
        raise ImportError("The MCP SDK isn't installed. Run: pip install 'agentmem[mcp]'") from exc

    resolved = state_dir or AgentMemConfig().state_dir
    server = FastMCP("agentmem")

    @server.tool()
    def recap() -> str:
        """Recap what AgentMem remembers about this project: the durable rules first,
        then the most recent session. Call this before starting work."""
        return _CORE["recap"](resolved)

    @server.tool()
    def search(query: str) -> str:
        """Search the project's memory for entries matching the query text.

        Args:
            query: What to look for, e.g. a file name, error, or convention.
        """
        return _CORE["search"](query, resolved)

    @server.tool()
    def bank() -> str:
        """Return the full durable, project-tier memory bank."""
        return _CORE["bank"](resolved)

    return server


def main() -> None:
    """Console-script entry point: serve over stdio. Logs go to stderr so they never
    corrupt the JSON-RPC stream on stdout."""
    import logging
    import sys

    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
