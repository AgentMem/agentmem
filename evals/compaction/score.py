"""Turn a Claude Code transcript into the numbers the compaction eval is judged on."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "agentmem" / "src"))

from agentmem.triggers import _normalize  # noqa: E402


def load(path: Path | str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in Path(path).read_text(errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def last_boundary(entries: list[dict[str, Any]]) -> int:
    idx = [i for i, e in enumerate(entries) if e.get("subtype") == "compact_boundary"]
    if not idx:
        raise ValueError("no compact_boundary in the transcript; the compact never happened")
    return idx[-1]


def _blocks(entry: dict[str, Any]) -> list[dict[str, Any]]:
    content = entry.get("message", {}).get("content", [])
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def tool_uses(entries: list[dict[str, Any]]) -> list[tuple[int, str, str, str]]:
    """(entry index, tool_use_id, tool name, command-ish input) per call."""
    out = []
    for i, e in enumerate(entries):
        if e.get("type") != "assistant":
            continue
        for b in _blocks(e):
            if b.get("type") == "tool_use":
                arg = b.get("input", {})
                cmd = arg.get("command") or json.dumps(arg, sort_keys=True)
                out.append((i, b.get("id", ""), b.get("name", ""), str(cmd)))
    return out


def results_by_id(entries: list[dict[str, Any]]) -> dict[str, tuple[bool, str]]:
    out = {}
    for e in entries:
        if e.get("type") != "user":
            continue
        for b in _blocks(e):
            if b.get("type") == "tool_result":
                text = b.get("content", "")
                if isinstance(text, list):
                    text = " ".join(str(x.get("text", "")) for x in text if isinstance(x, dict))
                out[b.get("tool_use_id", "")] = (bool(b.get("is_error")), str(text))
    return out


def last_assistant_text(entries: list[dict[str, Any]], after: int = 0) -> str:
    for e in reversed(entries[after:]):
        if e.get("type") != "assistant":
            continue
        texts = [b.get("text", "") for b in _blocks(e) if b.get("type") == "text"]
        if any(t.strip() for t in texts):
            return "\n".join(texts)
    return ""


def post_compact_metrics(
    entries: list[dict[str, Any]], wall_re: str, green_re: str
) -> dict[str, Any]:
    """From re-hitting a known wall after the compact to getting back to green.

    calls_to_green counts every tool call from the first post-compact wall hit up to
    and including the run that goes green. repeats counts a normalized command rerun
    after it failed with no edit in between, which is the behaviour users actually
    complain about; any mutation clears the slate, so a verify-after-fix never counts
    and the number can only undercount.
    """
    b = last_boundary(entries)
    wall, green = re.compile(wall_re), re.compile(green_re)
    calls = [c for c in tool_uses(entries) if c[0] > b]
    results = results_by_id(entries)

    wall_at = green_at = None
    for pos, (_, tid, _, _) in enumerate(calls):
        _, text = results.get(tid, (False, ""))
        if wall_at is None and wall.search(text):
            wall_at = pos
        if wall_at is not None and green.search(text):
            green_at = pos
            break

    mutating = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
    failed_since_edit: set[str] = set()
    repeats = 0
    for _, tid, name, cmd in calls:
        if name in mutating:
            failed_since_edit.clear()
            continue
        if name != "Bash":
            continue
        key = _normalize(cmd)
        if key in failed_since_edit:
            repeats += 1
        err, text = results.get(tid, (False, ""))
        if err or wall.search(text):
            failed_since_edit.add(key)
        else:
            failed_since_edit.discard(key)

    tokens_in = tokens_out = 0
    for e in entries[b + 1 :]:
        if e.get("type") == "assistant":
            u = e.get("message", {}).get("usage", {})
            tokens_in += int(u.get("input_tokens", 0) or 0)
            tokens_out += int(u.get("output_tokens", 0) or 0)

    return {
        "wall_reencountered": wall_at is not None,
        "recovered": green_at is not None,
        "calls_wall_to_green": (
            green_at - wall_at + 1 if green_at is not None and wall_at is not None else None
        ),
        "repeats_of_known_failures": repeats,
        "post_compact_tool_calls": len(calls),
        "post_compact_tokens_in": tokens_in,
        "post_compact_tokens_out": tokens_out,
    }
