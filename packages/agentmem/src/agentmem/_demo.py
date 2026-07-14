"""A small self-contained demo of the memory layer catching a repeated failure."""

from __future__ import annotations

import tempfile
from typing import Any

from .config import AgentMemConfig
from .llm.base import LLMResponse
from .schemas import Event, TokenUsage
from .session import MemorySession
from .tools import SAVE_KNOWLEDGE, SAVE_PROCEDURAL, ToolCall

TASK = "Make `pytest -q` pass. Constraint: do not modify the public signatures in api.py."

# The action agent's trajectory is scripted on both runs (we're demoing the memory
# agent, not a coding agent): two identical failures, then a course-correction once
# the reminder lands.
_FAIL = "FAILED tests/test_auth.py::test_token_expiry - AssertionError: expected 3600, got 60"

_TURNS: list[dict[str, object]] = [
    {
        "say": "Running the suite to see what's broken.",
        "events": [
            Event(kind="tool_call", tool_name="bash", text="pytest -q"),
            Event(kind="tool_result", tool_name="bash", ok=False, text=_FAIL),
        ],
    },
    {
        "say": "Looks like the call site passes the wrong timeout, tweaking make_token() and re-running.",
        "events": [
            Event(kind="tool_call", tool_name="bash", text="pytest -q"),
            Event(kind="tool_result", tool_name="bash", ok=False, text=_FAIL),
        ],
    },
    {
        # What the agent does here depends on whether it got the reminder.
        "say": "Fixing DEFAULT_TTL in config.py (the real source), not the call site.",
        "say_without_reminder": "Tweaking make_token() again, maybe a different argument this time.",
        "events": [
            Event(kind="tool_call", tool_name="bash", text="pytest -q"),
            Event(kind="tool_result", tool_name="bash", ok=True, text="4 passed in 0.12s"),
        ],
    },
]


def _usage() -> TokenUsage:
    return TokenUsage(input_tokens=0, output_tokens=0, model="scripted-demo")


def _call(name: str, idx: int, **args: object) -> ToolCall:
    return ToolCall(name=name, args=args, block_id=f"toolu_demo_{idx}")


class ScriptedProvider:
    """A canned provider. Phase 1 calls (which carry `tools`) and Phase 2 calls draw
    from separate scripts, popped in order."""

    model = "scripted-demo"

    def __init__(self) -> None:
        # Step 1: record the requirement and the first failure, then stay silent.
        # Step 2: after the second identical failure, upgrade the note to a diagnosis
        # and speak up before the agent loops a third time.
        self._phase1 = [
            LLMResponse(
                tool_calls=[
                    _call(
                        SAVE_KNOWLEDGE,
                        1,
                        tag="task",
                        content="Do not modify public signatures in api.py",
                    ),
                    _call(
                        SAVE_PROCEDURAL,
                        2,
                        tag="attempt",
                        content="pytest test_token_expiry fails: expected 3600 got 60 (TTL wrong)",
                    ),
                ],
                usage=_usage(),
            ),
            LLMResponse(
                tool_calls=[
                    _call(
                        SAVE_PROCEDURAL,
                        3,
                        id="P-001",
                        tag="diagnosis",
                        content="test_token_expiry failed 2x; call-site edits don't help, root cause is DEFAULT_TTL in config.py",
                    ),
                ],
                usage=_usage(),
            ),
        ]
        self._phase2 = [
            LLMResponse(text="<no_intervention/>", usage=_usage()),
            LLMResponse(
                text=(
                    "<context_for_action>\n"
                    "- (P-001) test_token_expiry has failed twice on the same TTL error; "
                    "the call site isn't the cause, fix DEFAULT_TTL in config.py instead of retrying the edit.\n"
                    "</context_for_action>"
                ),
                usage=_usage(),
            ),
        ]

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        if tools:
            return self._phase1.pop(0) if self._phase1 else LLMResponse(usage=_usage())
        return (
            self._phase2.pop(0)
            if self._phase2
            else LLMResponse(text="<no_intervention/>", usage=_usage())
        )


def run_demo(live: bool = False) -> int:
    print(f"\n  Task: {TASK}\n")
    print("  (An agent works the problem. AgentMem watches and only speaks when it matters.)\n")

    state_dir = tempfile.mkdtemp(prefix="agentmem-demo-")
    # One tool-round keeps the scripted provider simple; the reminder logic is the
    # point here, not the tool-use loop.
    config = AgentMemConfig(state_dir=state_dir, max_tool_rounds=1)
    provider = None if live else ScriptedProvider()
    if live:
        print("  [--live] Using a real model for the memory agent.\n")

    reminded_once = False
    # async_worker=False so each observe() finishes its step before we move on: the
    # demo reads like a transcript instead of racing a thread.
    with MemorySession(task=TASK, config=config, provider=provider, async_worker=False) as mem:
        for i, turn in enumerate(_TURNS, start=1):
            reminder = mem.pending_context()
            if reminder:
                reminded_once = True
                print("  ┌─ AgentMem reminds the agent ──────────────────────────────")
                for line in reminder.splitlines():
                    print(f"  │ {line}")
                print("  └───────────────────────────────────────────────────────────")
                say = turn["say"]
            else:
                say = turn.get("say_without_reminder", turn["say"])

            print(f"\n  turn {i}  agent: {say}")
            for event in turn["events"]:  # type: ignore[attr-defined]
                if event.kind == "tool_result":
                    print(f"          $ pytest -q  →  {'ok' if event.ok else 'FAIL'}: {event.text}")
            mem.observe(turn["events"])

        print("\n  Final memory bank:\n")
        print("  " + mem.bank.render_full().replace("\n", "\n  "))
        print(f"\n  Telemetry written to {state_dir}/telemetry.jsonl")
        print("  Try:  agentmem replay " + state_dir + "/telemetry.jsonl\n")

    if reminded_once:
        print(
            "  ✓ AgentMem caught the repeated failure and redirected the agent to the root cause.\n"
        )
        return 0
    print("  (no intervention fired, unexpected for the offline demo)\n")
    return 0
