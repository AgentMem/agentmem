"""The Terminal-Bench action loop, driven entirely offline: a scripted action
provider stands in for the model and the demo ScriptedProvider runs the memory
phases, so nothing here touches the network or needs harbor installed."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentmem._demo import ScriptedProvider
from agentmem.config import AgentMemConfig
from agentmem.llm.base import LLMResponse
from agentmem.schemas import TokenUsage
from agentmem.session import MemorySession
from agentmem.tools import ToolCall
from agentmem_evals.tbench.loop import ActionLoop, CountingProvider, cost_usd

_USAGE = TokenUsage(input_tokens=1000, output_tokens=100, model="claude-haiku-4-5")


def _bash(command: str, block_id: str = "") -> ToolCall:
    return ToolCall(name="bash", args={"command": command}, block_id=block_id or None)


def _resp(*calls: ToolCall, text: str = "") -> LLMResponse:
    return LLMResponse(text=text, tool_calls=list(calls), usage=_USAGE)


class FakeAction:
    """Pops canned responses and records every message window it was shown."""

    model = "claude-haiku-4-5"

    def __init__(self, script: list[LLMResponse]) -> None:
        self._script = script
        self.windows: list[list[dict[str, Any]]] = []

    def complete(self, *, system, messages, tools=None, max_tokens=1024):  # type: ignore[no-untyped-def]
        self.windows.append([dict(m) for m in messages])
        if not self._script:
            return _resp(text="out of script")
        return self._script.pop(0)


def _tool_use_ids_answered(window: list[dict[str, Any]]) -> bool:
    """Every tool_use block must be answered in the immediately following message."""
    for i, msg in enumerate(window):
        if msg["role"] != "assistant":
            continue
        uses = [b["id"] for b in msg["content"] if isinstance(b, dict) and b.get("type") == "tool_use"]
        if not uses:
            continue
        if i + 1 >= len(window):
            return False
        nxt = window[i + 1]["content"]
        answered = {b.get("tool_use_id") for b in nxt if isinstance(b, dict)}
        if not set(uses) <= answered:
            return False
    return True


def _memory_session(tmp_path: Path) -> MemorySession:
    return MemorySession(
        task="make the tests pass",
        provider=ScriptedProvider(),
        async_worker=False,
        config=AgentMemConfig(state_dir=str(tmp_path), max_tool_rounds=1),
    )


def test_exec_then_done_shapes_the_conversation() -> None:
    fake = FakeAction([_resp(_bash("ls")), _resp(ToolCall(name="task_done", args={"summary": "did it"}))])
    loop = ActionLoop(fake, "list the files", usd_cap=1.0)

    d1 = loop.next_decision()
    assert (d1.kind, d1.command) == ("exec", "ls")
    loop.record_exec(d1, "a.py\nb.py", "", 0)

    d2 = loop.next_decision()
    assert (d2.kind, d2.summary) == ("done", "did it")
    assert loop.stop_reason == "task_done"
    assert loop.turns == 2
    assert loop.spent_usd == cost_usd("claude-haiku-4-5", 2000, 200)
    assert _tool_use_ids_answered(fake.windows[-1])


def test_budget_cap_stops_the_loop() -> None:
    fake = FakeAction([_resp(_bash("ls")), _resp(_bash("pwd"))])
    loop = ActionLoop(fake, "task", usd_cap=cost_usd("claude-haiku-4-5", 1000, 100))

    d1 = loop.next_decision()
    loop.record_exec(d1, "ok", "", 0)
    d2 = loop.next_decision()
    assert (d2.kind, d2.reason) == ("stop", "budget")
    assert len(fake.windows) == 1  # the second model call never happened


def test_repeated_failure_gets_a_reminder_injected(tmp_path: Path) -> None:
    script = [_resp(_bash("pytest -q")) for _ in range(6)]
    fake = FakeAction(script)
    loop = ActionLoop(fake, "make the tests pass", memory=_memory_session(tmp_path), usd_cap=1.0)

    for _ in range(5):
        d = loop.next_decision()
        if d.kind != "exec":
            break
        loop.record_exec(d, "", "FAILED test_token_expiry - expected 3600 got 60", 1)
        if loop.reminders_injected:
            break

    assert loop.reminders_injected >= 1
    flat = [
        b.get("text", "")
        for w in fake.windows
        for m in w
        if m["role"] == "user"
        for b in m["content"]
        if isinstance(b, dict) and b.get("type") == "text"
    ]
    assert any("[agentmem reminder]" in t and "DEFAULT_TTL" in t for t in flat)
    loop.close()


def test_baseline_never_sees_memory_text() -> None:
    fake = FakeAction([_resp(_bash("pytest -q")) for _ in range(4)])
    loop = ActionLoop(fake, "make the tests pass", usd_cap=1.0)
    for _ in range(3):
        d = loop.next_decision()
        loop.record_exec(d, "", "FAILED test_token_expiry", 1)
    assert loop.reminders_injected == 0
    assert not any(e["type"] == "inject" for e in loop.transcript)
    joined = str(fake.windows)
    assert "[agentmem reminder]" not in joined


def test_parallel_tool_calls_all_get_results() -> None:
    two = _resp(_bash("ls", "id_a"), _bash("pwd", "id_b"))
    fake = FakeAction([two, _resp(ToolCall(name="task_done", args={}))])
    loop = ActionLoop(fake, "task", usd_cap=1.0)

    d = loop.next_decision()
    assert (d.command, d.skipped_ids) == ("ls", ["id_b"])
    loop.record_exec(d, "a.py", "", 0)

    assert loop.next_decision().kind == "done"
    assert _tool_use_ids_answered(fake.windows[-1])
    results = [b for b in fake.windows[-1][-1]["content"] if b.get("type") == "tool_result"]
    assert {r["tool_use_id"] for r in results} == {"id_a", "id_b"}


def test_window_trims_whole_pairs_and_keeps_the_instruction() -> None:
    fake = FakeAction([_resp(_bash(f"step {i}", f"id_{i}")) for i in range(8)])
    loop = ActionLoop(fake, "the instruction", usd_cap=1.0, keep_pairs=2)
    for _ in range(7):
        d = loop.next_decision()
        loop.record_exec(d, "fine", "", 0)

    last = fake.windows[-1]
    assert len(last) <= 1 + 2 * 2 + 1
    first_text = " ".join(b.get("text", "") for b in last[0]["content"])
    assert "the instruction" in first_text and "elided" in first_text
    assert _tool_use_ids_answered(last)


def test_no_tool_call_nudges_once_then_stops() -> None:
    fake = FakeAction([_resp(text="thinking..."), _resp(text="still thinking")])
    loop = ActionLoop(fake, "task", usd_cap=1.0)
    d = loop.next_decision()
    assert (d.kind, d.reason) == ("stop", "no_tool_call")
    assert loop.turns == 2  # original turn plus the one nudge


def test_long_output_is_truncated() -> None:
    fake = FakeAction([_resp(_bash("cat big", "id_c")), _resp(ToolCall(name="task_done", args={}))])
    loop = ActionLoop(fake, "task", usd_cap=1.0, output_char_cap=500)
    d = loop.next_decision()
    loop.record_exec(d, "x" * 5000, "", 0)
    loop.next_decision()
    result = next(
        b for b in fake.windows[-1][-1]["content"] if b.get("type") == "tool_result"
    )
    assert len(result["content"]) < 700
    assert "truncated" in result["content"]


def test_counting_provider_totals_spend() -> None:
    counted = CountingProvider(FakeAction([_resp(_bash("ls"))]))
    counted.complete(system="s", messages=[{"role": "user", "content": []}])
    assert (counted.input_tokens, counted.output_tokens) == (1000, 100)
    assert counted.usd == cost_usd("claude-haiku-4-5", 1000, 100)


def test_task_cap_covers_memory_spend_too() -> None:
    fake = FakeAction([_resp(_bash("ls")), _resp(_bash("pwd"))])
    cap = cost_usd("claude-haiku-4-5", 1000, 100) * 3  # room for several action turns
    loop = ActionLoop(fake, "task", usd_cap=cap, extra_cost=lambda: cap)  # memory ate it all
    d = loop.next_decision()
    assert (d.kind, d.reason) == ("stop", "budget")
    assert len(fake.windows) == 0  # not a single action call once the cap is gone
