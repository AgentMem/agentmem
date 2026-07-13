"""Phase 1: maintain the bank through tool calls.

One LLM call, optionally a second round so the model can see the result of its edits
before deciding it's done. Errors here are the caller's to swallow; Phase 1's job is
to return a bank, and worst case that's the one it started with.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..bank import AppliedCall, BankLimits, apply_tool_calls, budget_warnings
from ..config import AgentMemConfig
from ..llm.base import LLMProvider, LLMResponse
from ..schemas import MemoryBank, TokenUsage, render_tiered_for_agent
from ..tools import MEMORY_LINK_SCHEMA, TOOL_SCHEMAS, ToolCall
from .prompts import phase1_system, phase1_user_content


@dataclass
class Phase1Result:
    bank: MemoryBank
    applied: list[AppliedCall] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)


def run_phase1(
    provider: LLMProvider,
    config: AgentMemConfig,
    task: str,
    window: str,
    bank: MemoryBank,
    step: int,
    *,
    project_bank: MemoryBank | None = None,
) -> Phase1Result:
    limits = BankLimits.from_config(config)
    bank_render = render_tiered_for_agent(
        bank,
        project_bank,
        session_cap=config.continual_session_render_cap,
        project_cap=config.continual_project_render_cap,
    )
    user = phase1_user_content(task, window, bank_render, budget_warnings(bank, limits))
    messages: list[dict[str, Any]] = [{"role": "user", "content": user}]

    tools = [*TOOL_SCHEMAS, MEMORY_LINK_SCHEMA] if config.causal_enabled else TOOL_SCHEMAS
    system = phase1_system(config.causal_enabled)

    working = bank
    applied: list[AppliedCall] = []
    usage = TokenUsage()
    calls_made = 0

    for _ in range(config.max_tool_rounds):
        resp = provider.complete(
            system=system,
            messages=messages,
            tools=tools,
            max_tokens=config.max_output_tokens,
        )
        usage = usage + resp.usage

        if not resp.tool_calls:
            break  # no edits => the model is done (the common case)

        update = apply_tool_calls(working, resp.tool_calls, step, limits)
        working = update.bank
        applied.extend(update.applied)
        calls_made += len(resp.tool_calls)

        # Feed the results back so the model can reference new ids or stop. Every
        # tool_use needs a matching tool_result, so we answer the whole round.
        messages.append(_assistant_turn(resp))
        messages.append(_tool_result_turn(resp.tool_calls, update.applied))

        # Soft cap between rounds. We never cut a round mid-flight: that would orphan
        # tool_use blocks and the next request would 400.
        if calls_made >= config.max_tool_calls_per_step:
            break

    return Phase1Result(bank=working, applied=applied, usage=usage)


def _assistant_turn(resp: LLMResponse) -> dict[str, Any]:
    """Rebuild the assistant turn from text + tool calls (plain dicts, provider-neutral)."""
    content: list[dict[str, Any]] = []
    if resp.text:
        content.append({"type": "text", "text": resp.text})
    for tc in resp.tool_calls:
        content.append({"type": "tool_use", "id": tc.block_id, "name": tc.name, "input": tc.args})
    return {"role": "assistant", "content": content}


def _tool_result_turn(calls: list[ToolCall], applied: list[AppliedCall]) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = []
    # applied is one entry per call, then any evictions; strict=False drops that tail.
    for call, result in zip(calls, applied, strict=False):
        blocks.append(
            {"type": "tool_result", "tool_use_id": call.block_id, "content": _describe(result)}
        )
    return {"role": "user", "content": blocks}


def _describe(result: AppliedCall) -> str:
    if result.effect == "created":
        return f"Saved as {result.entry_id}." + (f" ({result.note})" if result.note else "")
    if result.effect == "updated":
        return f"Updated {result.entry_id}."
    if result.effect == "deleted":
        return f"Deleted {result.entry_id}."
    if result.effect == "status_updated":
        return "Status updated."
    if result.effect == "linked":
        return f"Linked ({result.note})."
    if result.effect == "unlinked":
        return "Link removed."
    if result.effect == "rejected":
        return f"No change: {result.note}."
    return result.effect
