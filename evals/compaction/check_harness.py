#!/usr/bin/env python3
"""Run the whole compaction harness against the mock CLI. No key, no network, $0.

The driver, the /compact detection and the scorer are exactly what the paid run
uses; only the CLI underneath is scripted. The two arms are scripted to differ,
so this also proves the instrument can detect the difference it claims to measure.

    uv run python evals/compaction/check_harness.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from driver import Driver  # noqa: E402
from score import last_assistant_text, load, post_compact_metrics  # noqa: E402

WALL_RE = r"PytestRemovedIn10Warning"
GREEN_RE = r"\d+ passed"
TICKETS = [
    "Run the test suite and fix whatever blocks it.",
    "Do chore two.",
    "Do chore three.",
    "Start a clean branch from origin/main and run the suite again.",
]
PROBE = "What did you fix earlier in this project, and why? Be specific about files."


def run_arm(arm: str, tmp: Path) -> dict:
    transcript = tmp / f"{arm}.jsonl"
    d = Driver(
        [
            sys.executable,
            str(HERE / "mock_claude.py"),
            "--transcript",
            str(transcript),
            "--arm",
            arm,
        ],
        transcript,
    )
    d.start()
    try:
        for ticket in TICKETS[:3]:
            d.send(ticket)
            d.wait_idle(quiet=1.0, timeout=30)
        d.compact(timeout=30)
        d.send(TICKETS[3])
        d.wait_idle(quiet=1.0, timeout=30)
        d.send(PROBE)
        d.wait_idle(quiet=1.0, timeout=30)
    finally:
        d.stop()
    entries = load(transcript)
    return {
        "metrics": post_compact_metrics(entries, WALL_RE, GREEN_RE),
        "probe": last_assistant_text(entries),
    }


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="compaction-check-"))
    none, memory = run_arm("none", tmp), run_arm("memory", tmp)

    for arm, r in (("none", none), ("memory", memory)):
        m = r["metrics"]
        print(
            f"{arm:7} wall={m['wall_reencountered']} recovered={m['recovered']} "
            f"calls_to_green={m['calls_wall_to_green']} repeats={m['repeats_of_known_failures']}"
        )

    nm, mm = none["metrics"], memory["metrics"]
    assert nm["wall_reencountered"] and mm["wall_reencountered"], "wall never re-hit post-compact"
    assert nm["recovered"] and mm["recovered"], "an arm never got back to green"
    assert mm["calls_wall_to_green"] < nm["calls_wall_to_green"], "scorer missed the gap"
    assert mm["repeats_of_known_failures"] == 0, "memory arm should not repeat known failures"
    assert nm["repeats_of_known_failures"] >= 2, "scorer missed the repeated failures"
    assert "test_basic.py" in memory["probe"], "probe capture lost the grounded answer"
    assert "auth" in none["probe"], "probe capture lost the confabulated answer"

    print("\nOK: driver drives, /compact is detected from the boundary marker, and the")
    print("scorer separates the two arms it was built to separate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
