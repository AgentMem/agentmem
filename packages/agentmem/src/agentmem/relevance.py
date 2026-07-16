"""Float the entries that match what the agent is looking at right now.

The bank is ordered by salience, which is a good prior and a bad fit for one moment:
an old diagnosis of the exact error on screen can sit below a fresh, generic note and
fall off the render cap, so Phase 2 never sees it. This re-orders by relevance to the
current window first, salience within that, so a matching entry survives the cap.

It only re-orders entries the bank already holds; it never invents one, and Phase 2
still decides whether to speak. Off by default, gated by config.relevance_boost, until
a measured run shows recall improves.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .schemas import MemoryEntry

# Code-shaped tokens: a file name, a dotted or snake_case identifier. Prose is ignored,
# so a shared token means the entry and the window are about the same concrete thing.
_CODEISH = re.compile(
    r"""
    [A-Za-z0-9_./-]*\.(?:py|yaml|yml|txt|json|toml|cfg|sh|md)
    | [A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*
    | [a-z_]{3,}_[a-z_]{3,}
    """,
    re.X,
)
_GENERIC = {"__init__", "setup.py", "test.py", "tests.py", "conftest.py"}


def tokens(text: str) -> set[str]:
    out = set()
    for raw in _CODEISH.findall(text or ""):
        tok = raw.split("/")[-1].lower()
        if len(tok) >= 5 and tok not in _GENERIC:
            out.add(tok)
    return out


def relevance(entry: MemoryEntry, window_tokens: set[str]) -> int:
    """How many distinctive tokens this entry shares with the window."""
    if not window_tokens:
        return 0
    return len(tokens(entry.content) & window_tokens)


def order(entries: list[MemoryEntry], window: str) -> list[MemoryEntry]:
    """Stable re-order: entries sharing more tokens with the window come first, and the
    incoming salience order breaks ties, so with an empty or unmatched window this is
    the identity.
    """
    wt = tokens(window)
    if not wt:
        return list(entries)
    return sorted(entries, key=lambda e: relevance(e, wt), reverse=True)
