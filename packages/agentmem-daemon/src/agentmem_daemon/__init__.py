"""AgentMem daemon: a localhost HTTP bridge between Claude Code hooks and AgentMem."""

from __future__ import annotations

from typing import Any

__version__ = "0.1.0.dev0"


def create_app(factory: Any = None, config: Any = None) -> Any:
    """Build the FastAPI app.

    Imported lazily so `import agentmem_daemon` works even without FastAPI installed;
    you only need the `serve` extra to actually run it.
    """
    from .app import create_app as _create_app

    return _create_app(factory=factory, config=config)
