#!/usr/bin/env python3
"""Run the real tau2 orchestrator on the mock domain with every model call stubbed.

The unit tests call the adapter directly; this checks the wiring they cannot see, and
needs no network, GPU or key. Run it before renting anything:

    .venv-tau2/bin/python evals/tau2/check_adapter.py
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import tau2.agent.llm_agent as llm_agent_mod
import tau2.user.user_simulator as user_mod
from agentmem.config import AgentMemConfig
from agentmem.llm.base import LLMResponse
from agentmem.schemas import TokenUsage
from agentmem.session import MemorySession
from agentmem.tools import SAVE_KNOWLEDGE, ToolCall
from agentmem.triggers import every_n
from agentmem_evals.tau2.agent import REMINDER_PREFIX, MemoryRun, register_agentmem_agent
from tau2.data_model.message import AssistantMessage, UserMessage
from tau2.data_model.simulation import TextRunConfig
from tau2.registry import registry
from tau2.runner.batch import run_single_task
from tau2.runner.helpers import get_tasks

SEEN: list[list] = []
_USAGE = TokenUsage(input_tokens=10, output_tokens=5, model="stub")


class StubMemoryProvider:
    """Stands in for the memory model across every call it makes.

    Saving is not optional: the injector drops a bullet whose id is not in the bank.
    Neither is routing by prompt: Phase 2, consolidation, promotion and the evaluator
    are all tool-less calls with different reply grammars, and one canned answer
    satisfies at most one of them."""

    model = "stub"

    def __init__(self) -> None:
        self.saved = False
        self.calls: list[str] = []

    def complete(self, *, system, messages, tools=None, max_tokens=1024):  # noqa: ANN001
        if tools:
            self.calls.append("phase1")
            if self.saved:
                return LLMResponse(usage=_USAGE)
            self.saved = True
            return LLMResponse(
                tool_calls=[
                    ToolCall(
                        name=SAVE_KNOWLEDGE,
                        args={"tag": "task", "content": "Always confirm the task id first"},
                        block_id="toolu_probe_1",
                    )
                ],
                usage=_USAGE,
            )
        if "Outcome Evaluator" in system:
            # Positive, because this is what turns a score into reinforcement, and an
            # unreinforced entry is never promoted.
            self.calls.append("evaluator")
            return LLMResponse(
                text='[{"step": 1, "reward": 0.9, "label": "changed_behavior_good", '
                '"why": "the reminder landed before the action"}]',
                usage=_USAGE,
            )
        if "standing rule" in system:  # PROMOTION_SYSTEM
            self.calls.append("promotion")
            return LLMResponse(text="[1] [rule] Confirm the task id before acting", usage=_USAGE)
        if "merge" in system.lower() or "consolidat" in system.lower():
            self.calls.append("consolidation")
            return LLMResponse(text="", usage=_USAGE)
        self.calls.append("phase2")
        return LLMResponse(
            text=(
                "<context_for_action>\n"
                "- (K-001) confirm the task id before acting\n"
                "</context_for_action>"
            ),
            usage=_USAGE,
        )


def stub_agent_generate(*, model, messages, tools=None, call_name=None, **kwargs):  # noqa: ANN001
    SEEN.append(list(messages))
    return AssistantMessage(role="assistant", content="Anything else I can help with?")


def stub_user_generate(*, model, messages, tools=None, call_name=None, **kwargs):  # noqa: ANN001
    """Says one thing, hears back, leaves. It must speak first or the agent never
    takes a turn. Counted from the conversation, not a global, which would leak
    across tickets."""
    prior = [m for m in messages if getattr(m, "role", "") != "system"]
    if len(prior) >= 2:
        return UserMessage(role="user", content="That is all, thanks. ###STOP###")
    return UserMessage(role="user", content="Hi, I need help with my task please.")


def main() -> int:
    # Each module bound `generate` at import; missing one reaches a real endpoint.
    llm_agent_mod.generate = stub_agent_generate
    user_mod.generate = stub_user_generate

    tmp = Path(tempfile.mkdtemp(prefix="tau2-check-"))
    mem_provider = StubMemoryProvider()
    run = MemoryRun(
        MemorySession(
            task="Handle customer service tickets",
            provider=mem_provider,
            trigger=every_n(1),
            async_worker=False,
            session_id="tau2-mock",
            # Off by default, and reinforcement lives inside the graded path, so
            # leaving it off means nothing is ever promoted. run_live.py sets it too.
            config=AgentMemConfig(
                state_dir=str(tmp / "mem"), advantage_enabled=True, advantage_gate=False
            ),
        )
    )
    name = register_agentmem_agent(run, name="agentmem-check")
    assert name in registry.get_agents(), "the agent never made it into tau2's registry"
    print(f"registered: {name}")
    print(f"agents tau2 now knows: {sorted(registry.get_agents())}")

    # Four, not one: an entry must live through 3 boundaries before it is promoted.
    tasks = get_tasks(task_set_name="mock", task_split_name=None, num_tasks=4)
    print(f"mock domain tickets: {[t.id for t in tasks]}")

    config = TextRunConfig(
        domain="mock",
        agent=name,
        llm_agent="stub-model",
        llm_args_agent={},
        user="user_simulator",  # dummy_user is solo-mode only
        llm_user="stub-model",
        llm_args_user={},
        num_trials=1,
        max_steps=4,
        max_concurrency=1,
    )
    # Ticket by ticket, as run_live does: the reward is handed back before the next.
    sims = []
    for task in tasks:
        try:
            sim = run_single_task(config, task, save_dir=tmp / "runs")
        except Exception as exc:
            print(f"  ticket {task.id}: {type(exc).__name__}: {exc}")
            continue
        sims.append(sim)
        reward = getattr(getattr(sim, "reward_info", None), "reward", 0.0) or 0.0
        # Forced: the stub solves nothing, so every real reward is 0 and promotion
        # could not fire however correct the wiring. The path is what is under test.
        run.end_ticket(1.0)
        print(f"  ticket {task.id}: real reward {reward}, ended at 1.0 for this check")
    print(f"simulations finished: {len(sims)}")
    assert sims, "tau2 ran nothing, so nothing here was checked"
    for sim in sims:
        print(f"  termination: {sim.termination_reason}")
    print(f"agent turns taken: {len(SEEN)}")
    assert SEEN, "the agent never took a turn, so the injection path was never reached"

    injected = any(REMINDER_PREFIX in str(getattr(m, "content", "") or "") for w in SEEN for m in w)
    print(f"a reminder reached the model: {injected}")
    assert injected, "the memory arm never injected; the adapter is not wired in"

    leaked = [
        m
        for sim in sims
        for m in (sim.messages or [])
        if REMINDER_PREFIX in str(getattr(m, "content", "") or "")
    ]
    print(f"reminders left in the graded trajectory: {len(leaked)}")
    assert not leaked, "a reminder leaked into the trajectory tau2 grades"

    print(f"ticket boundaries the bank saw: {run.tickets_ended} (tickets that ran: {len(sims)})")
    assert run.tickets_ended == len(sims), "every ticket that ran should have ended exactly once"
    print(f"memory-model calls by kind: {sorted(set(mem_provider.calls))}")

    run.close()

    # Ticket N+1 must open a bank ticket N wrote, or the arm is a scratchpad with
    # extra steps, and it would still have passed every check above.
    banked = MemorySession(
        task="Handle customer service tickets",
        provider=StubMemoryProvider(),
        trigger=every_n(1),
        async_worker=False,
        session_id="next-ticket",
        config=AgentMemConfig(state_dir=str(tmp / "mem")),
    )
    carried = dict(banked.project_bank.knowledge) | dict(banked.project_bank.procedural)
    banked.close()
    print(f"entries the next ticket inherits: {sorted(carried)}")
    assert carried, "nothing was promoted, so nothing would carry between tickets"

    print("\nOK: the real orchestrator ran the memory agent, the reminder reached the")
    print("model, it left nothing behind in the record tau2 scores, and what it")
    print("learned is waiting in the project bank for the next ticket.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
