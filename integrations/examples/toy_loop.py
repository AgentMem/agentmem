"""Wrapping your own agent loop with AgentMem.

The integration is small: read `pending_context()` before each turn, feed events to
`observe()` after. This script is a runnable template. The "action agent" here is a
stand-in that decides what to do based on whether it got a reminder; swap in your own
harness and drop the `provider=` override to use a real model.

Run it:

    python integrations/examples/toy_loop.py
"""

from __future__ import annotations

from agentmem import MemorySession, triggers
from agentmem._demo import ScriptedProvider  # offline stand-in for a real LLM
from agentmem.schemas import Event

TASK = "Make the tests pass without changing the public API."


def action_agent(memory_context: str | None, attempt: int) -> tuple[str, bool]:
    """Stand-in for your real agent.

    Returns (what it did, whether the tests passed). The only thing worth noticing:
    once AgentMem hands back a reminder, the agent stops repeating itself.
    """
    if memory_context and "DEFAULT_TTL" in memory_context:
        return ("fix DEFAULT_TTL in config.py", True)
    if attempt >= 3:
        return ("give up", False)
    return ("tweak the call site again", False)


def main() -> None:
    # provider=ScriptedProvider() keeps this offline. Delete it to use a real model
    # (needs ANTHROPIC_API_KEY); everything else stays the same.
    mem = MemorySession(
        task=TASK,
        provider=ScriptedProvider(),
        trigger=triggers.default(),
        async_worker=False,  # deterministic for a demo; drop it for real async use
    )

    try:
        for attempt in range(1, 5):
            reminder = mem.pending_context()
            if reminder:
                print(f"\n[AgentMem]\n{reminder}")

            did, passed = action_agent(reminder, attempt)
            print(f"turn {attempt}: agent -> {did}  ({'pass' if passed else 'fail'})")

            mem.observe(
                [
                    Event(kind="tool_call", tool_name="bash", text="pytest -q"),
                    Event(
                        kind="tool_result",
                        tool_name="bash",
                        ok=passed,
                        text="ok" if passed else "FAILED test_token_expiry",
                    ),
                ]
            )
            if passed:
                print("\ndone, tests pass.")
                break

        print("\nFinal memory bank:")
        print(mem.bank.render_full())
    finally:
        mem.close()


if __name__ == "__main__":
    main()
