"""AgentMem hub: the hosted, multi-tenant team feed over action receipts."""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__", "create_app"]


def __getattr__(name: str) -> object:
    # Lazy so `import agentmem_hub` does not require FastAPI unless the app is built.
    if name == "create_app":
        from .app import create_app

        return create_app
    raise AttributeError(name)
