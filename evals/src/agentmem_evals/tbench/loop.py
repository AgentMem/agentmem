"""The action loop both arms share; pure and sync so tests can drive it offline."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agentmem.llm.base import LLMProvider, LLMResponse
from agentmem.session import MemorySession

# USD per million tokens (input, output).
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-opus-4-8": (5.0, 25.0),
}
# When the model isn't in the table, assume Sonnet-tier prices rather than undercounting.
_FALLBACK_PRICE = (3.0, 15.0)

# litellm routes to a server you run yourself. That bills by the GPU hour, not the
# token, so per-token cost is zero and the per-trial cap stops binding: a run on your
# own hardware ends on turns or on the task, never on money. Pricing these at the
# fallback rate would kill trials on the first turn.
_SELF_HOSTED_ROUTES = ("hosted_vllm/", "vllm/", "ollama/", "ollama_chat/", "lm_studio/")


def is_self_hosted(model: str) -> bool:
    return model.removeprefix("litellm/").startswith(_SELF_HOSTED_ROUTES)

BASH_TOOL: dict[str, Any] = {
    "name": "bash",
    "description": (
        "Run one shell command in the task machine and get its output back. "
        "Commands run non-interactively; never start editors, pagers, or REPLs."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The command to run."},
            "timeout_sec": {
                "type": "integer",
                "description": "Max seconds to let it run (default 60, max 300).",
            },
        },
        "required": ["command"],
    },
}

DONE_TOOL: dict[str, Any] = {
    "name": "task_done",
    "description": "Declare the task finished. Call this once the goal is met.",
    "input_schema": {
        "type": "object",
        "properties": {"summary": {"type": "string", "description": "One line on what was done."}},
        "required": [],
    },
}

SYSTEM_PROMPT = """You are a capable engineer operating a Linux machine through a terminal.

Work the task with bash calls, one command per turn. Look before you leap: inspect
files and state before changing them. Keep commands non-interactive (use flags like
-y, --no-pager, | cat). When the goal is verifiably met, call task_done. Every reply
must be exactly one tool call."""

_REMINDER_PREFIX = "[agentmem reminder]"
_SKIPPED_NOTE = "skipped: one command per turn, rerun it next turn if still needed"


@dataclass
class Decision:
    """What the loop wants the driver to do next."""

    kind: str  # "exec" | "done" | "stop"
    command: str = ""
    timeout_sec: int = 60
    tool_id: str = ""
    skipped_ids: list[str] = field(default_factory=list)
    summary: str = ""
    reason: str = ""


class CountingProvider:
    """Wraps any provider and totals what it spends. Used for the memory session's
    provider so the report can show the full price of the memory arm, not just the
    action calls."""

    def __init__(self, inner: LLMProvider) -> None:
        self._inner = inner
        self.model = inner.model
        self.input_tokens = 0
        self.output_tokens = 0

    def complete(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        resp = self._inner.complete(
            system=system, messages=messages, tools=tools, max_tokens=max_tokens
        )
        self.input_tokens += resp.usage.input_tokens
        self.output_tokens += resp.usage.output_tokens
        return resp

    @property
    def usd(self) -> float:
        return cost_usd(self.model, self.input_tokens, self.output_tokens)


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    if is_self_hosted(model):
        return 0.0
    inp, out = PRICES.get(model, _FALLBACK_PRICE)
    return (input_tokens * inp + output_tokens * out) / 1_000_000


def _assistant_content(resp: LLMResponse) -> list[dict[str, Any]]:
    """The assistant turn to append. Prefer the provider's raw blocks; rebuild them
    from the parsed pieces when a provider doesn't keep the raw turn."""
    raw = resp.raw_assistant_content
    if isinstance(raw, list) and raw:
        blocks: list[dict[str, Any]] = []
        for b in raw:
            blocks.append(b if isinstance(b, dict) else b.model_dump())
        return blocks
    rebuilt: list[dict[str, Any]] = []
    if resp.text:
        rebuilt.append({"type": "text", "text": resp.text})
    for i, call in enumerate(resp.tool_calls):
        rebuilt.append(
            {
                "type": "tool_use",
                "id": call.block_id or f"toolu_rebuilt_{i}",
                "name": call.name,
                "input": call.args,
            }
        )
    if not rebuilt:
        rebuilt.append({"type": "text", "text": "(empty turn)"})
    return rebuilt


def _truncate(text: str, cap: int) -> str:
    """Keep head and tail; the middle of long output is the least useful part."""
    if len(text) <= cap:
        return text
    head = cap * 2 // 3
    tail = cap - head
    dropped = len(text) - cap
    return f"{text[:head]}\n... [{dropped} chars truncated] ...\n{text[-tail:]}"


class ActionLoop:
    """One task attempt. Drive it with next_decision()/record_exec() until a
    Decision with kind done or stop comes back."""

    def __init__(
        self,
        provider: LLMProvider,
        instruction: str,
        *,
        memory: MemorySession | None = None,
        extra_cost: Callable[[], float] | None = None,
        max_turns: int = 30,
        usd_cap: float = 0.25,
        output_char_cap: int = 2000,
        keep_pairs: int = 20,
        max_tokens: int = 1024,
    ) -> None:
        self._provider = provider
        self._memory = memory
        self._extra_cost = extra_cost
        self._max_turns = max_turns
        self._usd_cap = usd_cap
        self._output_char_cap = output_char_cap
        self._keep_pairs = keep_pairs
        self._max_tokens = max_tokens

        self.turns = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.stop_reason = ""
        self.done_summary = ""
        self.reminders_injected = 0
        self.transcript: list[dict[str, Any]] = []

        self._nudged = False
        self._messages: list[dict[str, Any]] = [
            {"role": "user", "content": [{"type": "text", "text": instruction}]}
        ]
        if memory is not None:
            memory.observe(
                {
                    "kind": "message",
                    "role": "user",
                    "text": instruction[:2000],
                    "source": "instruction",
                }
            )

    @property
    def spent_usd(self) -> float:
        return cost_usd(self._provider.model, self.input_tokens, self.output_tokens)

    @property
    def total_usd(self) -> float:
        """Action spend plus whatever the extra_cost hook reports (the memory arm
        passes its memory provider's spend here, so the task cap covers both)."""
        extra = self._extra_cost() if self._extra_cost is not None else 0.0
        return self.spent_usd + extra

    def next_decision(self) -> Decision:
        if self.turns >= self._max_turns:
            return self._stop("max_turns")
        if self.total_usd >= self._usd_cap:
            return self._stop("budget")

        if self._memory is not None:
            reminder = self._memory.pending_context()
            if reminder:
                self._append_user_text(f"{_REMINDER_PREFIX}\n{reminder}")
                self.reminders_injected += 1
                self._log("inject", text=reminder)

        try:
            resp = self._provider.complete(
                system=SYSTEM_PROMPT,
                messages=self._window(),
                tools=[BASH_TOOL, DONE_TOOL],
                max_tokens=self._max_tokens,
            )
        except Exception as exc:  # noqa: BLE001 - a dead provider ends the attempt
            return self._stop(f"provider_error: {type(exc).__name__}: {exc}")

        self.turns += 1
        self.input_tokens += resp.usage.input_tokens
        self.output_tokens += resp.usage.output_tokens
        for i, call in enumerate(resp.tool_calls):
            if not call.block_id:
                call.block_id = f"toolu_rebuilt_{i}"
        self._messages.append({"role": "assistant", "content": _assistant_content(resp)})
        self._log(
            "model",
            text=resp.text[:400],
            tool_calls=[c.name for c in resp.tool_calls],
            usd=round(self.spent_usd, 6),
        )

        bash_calls = [c for c in resp.tool_calls if c.name == "bash"]
        done_calls = [c for c in resp.tool_calls if c.name == "task_done"]

        if bash_calls:
            first = bash_calls[0]
            others = [c for c in resp.tool_calls if c is not first]
            command = str(first.args.get("command", ""))
            timeout = int(first.args.get("timeout_sec", 60) or 60)
            return Decision(
                kind="exec",
                command=command,
                timeout_sec=max(1, min(timeout, 300)),
                tool_id=first.block_id or "",
                skipped_ids=[c.block_id or "" for c in others],
            )
        if done_calls:
            summary = str(done_calls[0].args.get("summary", ""))
            self.done_summary = summary
            self.stop_reason = "task_done"
            self._log("done", text=summary)
            return Decision(kind="done", summary=summary)

        # No tool call. Nudge once, then give up: a model that won't use tools
        # here isn't going to recover.
        if not self._nudged:
            self._nudged = True
            self._append_user_text(
                "Reply with exactly one tool call: bash to keep working, or task_done."
            )
            return self.next_decision()
        return self._stop("no_tool_call")

    def record_exec(
        self,
        decision: Decision,
        stdout: str,
        stderr: str,
        return_code: int,
        duration_s: float = 0.0,
    ) -> None:
        output = stdout if not stderr else f"{stdout}\n[stderr]\n{stderr}".strip()
        output = _truncate(output or "(no output)", self._output_char_cap)

        blocks: list[dict[str, Any]] = [
            {
                "type": "tool_result",
                "tool_use_id": decision.tool_id,
                "content": f"exit={return_code}\n{output}",
                "is_error": return_code != 0,
            }
        ]
        for skipped in decision.skipped_ids:
            blocks.append({"type": "tool_result", "tool_use_id": skipped, "content": _SKIPPED_NOTE})
        self._messages.append({"role": "user", "content": blocks})
        self._log(
            "exec",
            text=decision.command,
            exit=return_code,
            duration_s=round(duration_s, 2),
        )

        if self._memory is not None:
            self._memory.observe(
                [
                    {
                        "kind": "tool_call",
                        "tool_name": "bash",
                        "text": decision.command[:500],
                    },
                    {
                        "kind": "tool_result",
                        "tool_name": "bash",
                        "ok": return_code == 0,
                        "text": output[:1500],
                    },
                ]
            )

    def close(self, reward: float = 0.0) -> None:
        if self._memory is not None:
            self._memory.close(task_reward=reward)

    def _stop(self, reason: str) -> Decision:
        self.stop_reason = reason
        self._log("stop", text=reason)
        return Decision(kind="stop", reason=reason)

    def _append_user_text(self, text: str) -> None:
        """Add a text block to the conversation without creating back-to-back user
        turns: piggyback on the last message when it is already a user turn."""
        block = {"type": "text", "text": text}
        last = self._messages[-1]
        if last["role"] == "user":
            last["content"].append(block)
        else:
            self._messages.append({"role": "user", "content": [block]})

    def _window(self) -> list[dict[str, Any]]:
        """The messages actually sent: the instruction, an elision note when old
        turns were dropped, then the most recent exchanges, cut only at
        assistant-turn boundaries so tool pairs survive."""
        msgs = self._messages
        limit = 1 + self._keep_pairs * 2
        if len(msgs) <= limit:
            return msgs

        tail = msgs[-(limit - 1) :]
        while tail and tail[0]["role"] != "assistant":
            tail = tail[1:]
        first = dict(msgs[0])
        first["content"] = list(msgs[0]["content"]) + [
            {
                "type": "text",
                "text": f"[{len(msgs) - 1 - len(tail)} earlier messages elided]",
            }
        ]
        return [first, *tail]

    def _log(self, kind: str, **fields: Any) -> None:
        self.transcript.append({"t": round(time.time(), 3), "type": kind, **fields})
