"""Recall of the memory layer: when the bank already knew the wall, did it say so.

Precision is measured elsewhere (the audit's faithful/harmful). This is the other
half: of the times the agent hit a wall the bank had an entry for, how often did a
relevant reminder actually surface. attrs seed 2 is why it exists: the bank held the
diagnosis, the wall came back, and the one reminder that fired was about an unrelated
chore. High precision, and a recall of zero, are the same failure the tau2 null was.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "longdebug_causal"))

from grounding import candidates  # noqa: E402

# Tokens too generic to prove an entry is about a particular wall.
_GENERIC = {"python", "pytest", "tests", "test", "work", "failed", "error", "assert", "true"}


def signature(wall_text: str, bank_blob: str) -> set[str]:
    """The distinctive things a wall output and the bank have in common.

    A token has to look like code, be specific, and appear in both. If that set is
    empty the bank did not know this wall, and the wall does not count against recall.
    """
    bank = bank_blob.lower()
    out = set()
    for tok in candidates(wall_text):
        bare = tok.strip("`").split("/")[-1].split("(")[0].lower()
        if len(bare) < 5 or bare in _GENERIC:
            continue
        if bare in bank:
            out.add(bare)
    return out


def _mentions(text: str, sig: set[str]) -> bool:
    low = text.lower()
    return any(tok in low for tok in sig)


def recall_at_wall(
    calls: list[dict[str, Any]],
    reminders: list[dict[str, Any]],
    bank_blob: str,
    wall_re: str,
) -> dict[str, Any]:
    """Did a relevant reminder surface at a wall the bank could speak to.

    calls are the post-reset session's commands with outputs; reminders are the inject
    events from that session, each with its text and cited snapshots; bank_blob is all
    entry content the run ended with. Coarse on timing on purpose: it asks whether the
    layer surfaced its relevant knowledge in the session at all, which a run that
    fired an unrelated note has not.
    """
    wall = re.compile(wall_re, re.M)
    walls = [c for c in calls if wall.search(c.get("output", ""))]
    if not walls:
        return {"wall_hit": False, "bank_knew": False, "relevant_fired": False, "recall": None}

    sig: set[str] = set()
    for c in walls:
        sig |= signature(c["output"], bank_blob)
    bank_knew = bool(sig)

    relevant = False
    for r in reminders:
        blob = (r.get("text") or "") + " " + " ".join((r.get("snapshot") or {}).values())
        if _mentions(blob, sig):
            relevant = True
            break

    return {
        "wall_hit": True,
        "bank_knew": bank_knew,
        "relevant_fired": relevant,
        # Recall is only defined where the bank had something to surface.
        "recall": (1 if relevant else 0) if bank_knew else None,
        "signature": sorted(sig),
    }


def _load_run(report: Path, scratch: Path, wall_re: str) -> dict[str, Any]:
    import json

    d = {r["condition"]: r for r in json.loads(report.read_text())}
    mem = d["memory"]
    tel_path = scratch / "mem-memory" / "telemetry.jsonl"
    injects = [
        json.loads(line)
        for line in tel_path.read_text().splitlines()
        if line and '"decision": "inject"' in line
    ]
    n = mem["sessions"][-1]["reminders"]
    last = (
        [
            {"text": e.get("intervention_text", ""), "snapshot": e.get("cited_snapshot", {})}
            for e in injects[-n:]
        ]
        if n
        else []
    )
    blob = ""
    for bank_file in (scratch / "mem-memory" / "banks").glob("*.json"):
        bank = json.loads(bank_file.read_text()).get("bank", {})
        for tier in ("knowledge", "procedural", "archive"):
            for e in (bank.get(tier) or {}).values():
                blob += " " + e.get("content", "")
    return recall_at_wall(mem["final_session_calls"], last, blob, wall_re)


def main() -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(description="recall of the memory layer over repeat runs")
    ap.add_argument("--report", required=True, help="a repeat report json")
    ap.add_argument("--scratch", required=True, help="the run's mem-* keep-dir")
    ap.add_argument("--wall-re", required=True)
    args = ap.parse_args()
    r = _load_run(Path(args.report), Path(args.scratch), args.wall_re)
    print(json.dumps(r, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
