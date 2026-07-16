#!/usr/bin/env python3
"""A stand-in for the claude CLI that emits a schema-faithful transcript.

Field shapes are copied from a real ~/.claude/projects transcript, compact
boundary included, so the scorer is validated against what the real tool writes.
The scripted story is the click bit-rot flow: hit the pytest wall, fix it,
compact, hit it again on a clean branch. --arm decides whether the second
encounter is remembered (2 calls) or re-derived (7 calls with repeats).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

WALL = (
    "E pytest.PytestRemovedIn10Warning: Passing a non-Collection iterable\n"
    "ERROR tests/test_basic.py\n!!!! Interrupted: 1 error during collection !!!!"
)
GREEN = "590 passed, 21 skipped, 1 xfailed in 0.61s"
PYTEST = "python -m pytest tests/ -q"


class Transcript:
    def __init__(self, path: Path, session_id: str) -> None:
        self.path = path
        self.sid = session_id
        self.turn = 0

    def _write(self, entry: dict) -> None:
        base = {
            "uuid": str(uuid.uuid4()),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "sessionId": self.sid,
            "cwd": str(Path.cwd()),
            "version": "0.0.0-mock",
        }
        with self.path.open("a") as f:
            f.write(json.dumps(base | entry) + "\n")

    def user_text(self, text: str) -> None:
        self._write(
            {
                "type": "user",
                "message": {"role": "user", "content": [{"type": "text", "text": text}]},
            }
        )

    def assistant_text(self, text: str) -> None:
        self._write(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "model": "mock",
                    "content": [{"type": "text", "text": text}],
                    "usage": {"input_tokens": 900, "output_tokens": 60},
                },
            }
        )

    def tool(self, name: str, command: str, result: str, *, is_error: bool = False) -> None:
        tid = f"toolu_{uuid.uuid4().hex[:12]}"
        self._write(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "model": "mock",
                    "content": [
                        {"type": "tool_use", "id": tid, "name": name, "input": {"command": command}}
                    ],
                    "usage": {"input_tokens": 1200, "output_tokens": 40},
                },
            }
        )
        self._write(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "tool_use_id": tid,
                            "type": "tool_result",
                            "content": result,
                            "is_error": is_error,
                        }
                    ],
                },
            }
        )

    def compact(self) -> None:
        self._write(
            {
                "type": "system",
                "subtype": "compact_boundary",
                "content": "Conversation compacted",
                "level": "info",
                "isMeta": True,
                "compactMetadata": {"trigger": "manual", "preTokens": 118000, "postTokens": 9000},
            }
        )
        self._write(
            {
                "type": "user",
                "isCompactSummary": True,
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "Summary: maintenance work on click."}],
                },
            }
        )


def ticket_one(t: Transcript) -> None:
    t.tool("Bash", PYTEST, WALL, is_error=True)
    t.tool("Edit", "edit tests/test_basic.py wrap list(chain(", "ok")
    t.tool("Bash", PYTEST, GREEN)
    t.assistant_text("Fixed the pytest 9.1.1 vs pinned 7.4.0 collection error; suite green.")


def chore(t: Transcript, i: int) -> None:
    t.tool("Bash", f"grep -rn 'chore {i}' src/", "src/click/core.py: fine")
    t.assistant_text(f"Chore {i} done.")


def ticket_four(t: Transcript, arm: str) -> None:
    t.tool("Bash", "git switch -c ticket-5 origin/main", "Switched to a new branch 'ticket-5'")
    t.tool("Bash", PYTEST, WALL, is_error=True)
    if arm == "memory":
        t.tool("Edit", "edit tests/test_basic.py wrap list(chain(", "ok")
        t.tool("Bash", PYTEST, GREEN)
        t.assistant_text("Same collection wall as before the compact; reapplied the fix.")
        return
    t.tool("Bash", PYTEST, WALL, is_error=True)
    t.tool("Bash", "pip install 'pytest==7.4.0'", "ERROR: resolution impossible", is_error=True)
    t.tool("Bash", PYTEST, WALL, is_error=True)
    t.tool("Edit", "edit tests/test_basic.py guess parametrize ids", "ok")
    t.tool("Bash", PYTEST, WALL, is_error=True)
    t.tool("Edit", "edit tests/test_basic.py wrap list(chain(", "ok")
    t.tool("Bash", PYTEST, GREEN)
    t.assistant_text("Took a while to rediscover the parametrize issue; suite green now.")


def probe_answer(t: Transcript, arm: str) -> None:
    if arm == "memory":
        t.assistant_text(
            "Earlier I fixed tests/test_basic.py, wrapping a generator in list(chain(...)) "
            "because pytest 9.1.1 against the pinned 7.4.0 kills collection."
        )
    else:
        t.assistant_text(
            "I refactored the auth middleware in src/middleware/auth.ts and fixed "
            "a race condition in the database connection pool."
        )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--arm", choices=["none", "memory"], required=True)
    args = ap.parse_args()
    t = Transcript(Path(args.transcript), f"mock-{args.arm}")

    prompts = 0
    buf = b""
    while True:
        ch = sys.stdin.buffer.read(1)
        if not ch:
            return 0
        if ch not in (b"\r", b"\n"):
            buf += ch
            continue
        line, buf = buf.decode(errors="replace").strip(), b""
        if not line:
            continue
        if line == "/compact":
            t.compact()
            continue
        prompts += 1
        t.user_text(line)
        if prompts == 1:
            ticket_one(t)
        elif prompts in (2, 3):
            chore(t, prompts)
        elif prompts == 4:
            ticket_four(t, args.arm)
        else:
            probe_answer(t, args.arm)


if __name__ == "__main__":
    raise SystemExit(main())
