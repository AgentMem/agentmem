"""Per-session accounting of what the memory layer actually did.

`replay` prints the raw stream; this answers the question a user asks after a day
of work: did the thing earn its keep, and can I see each time it spoke up.
"""

from __future__ import annotations

from typing import Any


def summarize(entries: list[dict[str, Any]]) -> dict[str, Any]:
    sessions: dict[str, dict[str, Any]] = {}
    for e in entries:
        s = sessions.setdefault(
            str(e.get("session_id", "?")),
            {"steps": 0, "injects": 0, "edits": 0, "reminders": []},
        )
        s["steps"] += 1
        s["edits"] += len(e.get("tool_calls") or [])
        if e.get("decision") == "inject":
            s["injects"] += 1
            s["reminders"].append(
                {
                    "step": e.get("step"),
                    "ts": e.get("ts", ""),
                    "cited": e.get("cited_ids") or [],
                    "text": e.get("intervention_text") or "",
                }
            )
    return {
        "sessions": sessions,
        "steps": sum(s["steps"] for s in sessions.values()),
        "injects": sum(s["injects"] for s in sessions.values()),
        "edits": sum(s["edits"] for s in sessions.values()),
    }


def render(summary: dict[str, Any]) -> str:
    lines = [
        f"memory steps: {summary['steps']}   bank edits: {summary['edits']}   "
        f"reminders shown: {summary['injects']}"
    ]
    if summary["steps"] and not summary["injects"]:
        lines.append("every step chose silence, which is the default and usually correct")
    for sid, s in summary["sessions"].items():
        lines.append(f"\nsession {sid}: {s['steps']} steps, {s['injects']} reminders")
        for r in s["reminders"]:
            cited = ", ".join(r["cited"]) or "no citations"
            lines.append(f"  step {r['step']} ({cited})")
            for row in r["text"].splitlines():
                lines.append(f"    {row}")
    return "\n".join(lines)
