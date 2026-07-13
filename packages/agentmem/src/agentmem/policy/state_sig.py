"""Turn the situation at a memory-step into a bag of tokens.

Two similar situations should share most of their tokens, so a Jaccard overlap is a
good "have I seen a state like this before?" measure. Everything is bucketed and
stripped of specifics (paths, ids, exact counts) so, say, "pytest just failed with the
bank half full" collides across projects instead of being unique every time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..schemas import Event, MemoryBank


@dataclass
class DecisionContext:
    """What the advantage layer sees when Phase 2 is about to decide."""

    trigger: str = ""
    window: list[Event] = field(default_factory=list)
    bank: MemoryBank = field(default_factory=MemoryBank)
    steps_since_inject: int = 99
    task: str = ""


def state_signature(ctx: DecisionContext) -> list[str]:
    tokens: list[str] = []

    for reason in ctx.trigger.split("+"):
        if reason:
            tokens.append(f"trigger:{reason}")

    last = _last_tool_result(ctx.window)
    if last is not None:
        tokens.append(f"tool:{last.tool_name or 'tool'}:{'ok' if last.ok else 'fail'}")

    tokens.append(f"fails:{_count_bucket(_failed_results(ctx.window))}")
    tokens.append(f"repeat:{_count_bucket(_repeated_commands(ctx.window))}")
    tokens.append(f"since_inject:{_since_bucket(ctx.steps_since_inject)}")
    tokens.append(f"bankK:{_size_bucket(len(ctx.bank.knowledge))}")
    tokens.append(f"bankP:{_size_bucket(len(ctx.bank.procedural))}")

    cmd = _last_command(ctx.window)
    if cmd:
        tokens.append(f"cmd:{_strip_command(cmd)}")

    for word in _task_keywords(ctx.task):
        tokens.append(f"task:{word}")

    return tokens


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    union = sa | sb
    return len(sa & sb) / len(union) if union else 0.0


def _last_tool_result(window: list[Event]) -> Event | None:
    for event in reversed(window):
        if event.kind == "tool_result":
            return event
    return None


def _last_command(window: list[Event]) -> str:
    for event in reversed(window):
        if event.kind == "tool_call" and event.text:
            return event.text
    return ""


def _failed_results(window: list[Event]) -> int:
    return sum(1 for e in window if e.kind == "tool_result" and not e.ok)


def _repeated_commands(window: list[Event]) -> int:
    seen: set[str] = set()
    repeats = 0
    for event in window:
        if event.kind != "tool_call":
            continue
        norm = re.sub(r"\s+", " ", event.text.strip().lower())
        if norm and norm in seen:
            repeats += 1
        seen.add(norm)
    return repeats


def _count_bucket(n: int) -> str:
    if n <= 0:
        return "0"
    if n == 1:
        return "1"
    return "2+"


def _since_bucket(n: int) -> str:
    if n <= 2:
        return "0-2"
    if n <= 5:
        return "3-5"
    return "6+"


def _size_bucket(n: int) -> str:
    if n == 0:
        return "0"
    if n <= 5:
        return "1-5"
    if n <= 15:
        return "6-15"
    return "16+"


def _strip_command(cmd: str) -> str:
    """Normalize a command so variants collapse: drop paths, hex, quotes, and numbers."""
    cmd = cmd.strip().lower()
    cmd = re.sub(r"['\"][^'\"]*['\"]", "*", cmd)  # quoted strings
    cmd = re.sub(r"\b[0-9a-f]{8,}\b", "*", cmd)  # hashes
    cmd = re.sub(r"[\w./-]*/[\w./-]+", "*", cmd)  # paths
    cmd = re.sub(r"\b\d+\b", "*", cmd)  # bare numbers
    cmd = re.sub(r"\s+", " ", cmd)
    # Keep the program and the first flag/subcommand; the tail (test names, args)
    # varies too much to be a useful state feature.
    return " ".join(cmd.split()[:2])


_STOPWORDS = {
    "the",
    "a",
    "an",
    "to",
    "of",
    "in",
    "on",
    "and",
    "or",
    "for",
    "with",
    "without",
    "make",
    "fix",
    "add",
    "do",
    "not",
    "must",
    "is",
    "are",
    "this",
    "that",
    "it",
    "tests",
    "test",
    "pass",
    "all",
}


def _task_keywords(task: str, limit: int = 4) -> list[str]:
    words = re.findall(r"[a-z][a-z_]{3,}", task.lower())
    keywords: list[str] = []
    for word in words:
        if word not in _STOPWORDS and word not in keywords:
            keywords.append(word)
        if len(keywords) >= limit:
            break
    return keywords
