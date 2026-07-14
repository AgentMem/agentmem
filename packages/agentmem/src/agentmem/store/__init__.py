"""Store selection from a config string."""

from __future__ import annotations

from pathlib import Path

from .base import SessionInfo, Store
from .jsonfile import JsonFileStore
from .sqlite import SqliteStore

__all__ = ["Store", "SessionInfo", "JsonFileStore", "SqliteStore", "open_store"]


def open_store(spec: str = "json", state_dir: str = ".agentmem") -> Store:
    spec = spec.strip()

    if spec in ("", "json"):
        return JsonFileStore(state_dir)

    if spec.startswith("sqlite"):
        # Accept bare "sqlite" as well as a full "sqlite:///path" URL.
        _, _, path = spec.partition("///")
        db_path = path or str(Path(state_dir) / "agentmem.db")
        return SqliteStore(db_path)

    # A "scheme://" that isn't sqlite is an unsupported backend, not a path.
    if "://" in spec:
        raise ValueError(
            f"Unsupported store backend: {spec!r}. Use 'json', 'sqlite', or 'sqlite:///path.db'."
        )

    # Bare filesystem paths are a friendly shorthand: sniff the extension.
    if spec.endswith(".db") or spec.endswith(".sqlite"):
        return SqliteStore(spec)
    if spec.endswith(".json") or "/" in spec:
        return JsonFileStore(spec)

    raise ValueError(
        f"Unrecognized store spec: {spec!r}. Use 'json', 'sqlite', or 'sqlite:///path.db'."
    )
