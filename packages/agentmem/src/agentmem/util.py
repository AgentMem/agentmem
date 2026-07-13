"""Token estimation and text truncation helpers."""

from __future__ import annotations

# Rough heuristic. Good enough for budget checks and avoids a tokenizer dependency.
_CHARS_PER_TOKEN = 4


def approx_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)


def clip_to_tokens(text: str, max_tokens: int) -> str:
    """Trim text to roughly max_tokens, cutting the tail."""
    limit = max_tokens * _CHARS_PER_TOKEN
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + " …"


def truncate_middle(text: str, max_tokens: int) -> str:
    """Trim to roughly max_tokens by dropping the middle and keeping both ends.

    Tool output usually has the useful bits at the ends: the command, and the error
    it stopped on. Keep those, drop the noise in between.
    """
    limit = max_tokens * _CHARS_PER_TOKEN
    if len(text) <= limit:
        return text
    marker = "\n  … [truncated] …\n"
    keep = max(limit - len(marker), 0)
    head = keep * 2 // 3
    tail = keep - head
    return text[:head].rstrip() + marker + text[len(text) - tail :].lstrip()
