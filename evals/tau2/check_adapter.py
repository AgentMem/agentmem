#!/usr/bin/env python3
"""Drive the real tau2 orchestrator end to end with the LLM stubbed out.

The unit tests call the adapter's methods directly. This calls none of them: it hands
the agent to tau2 and lets tau2 run a real simulation on the mock domain, so what is
being checked is the wiring the tests cannot see. Whether the factory signature is
right, whether the orchestrator ever calls `stop`, whether a reminder survives into
the trajectory that gets graded.

No network, no GPU, no key. Run it before renting anything:

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
    """Stands in for the memory model across all four of the calls it makes.

    Saving is not optional: the injector only shows a bullet whose id it can find, so
    a Phase 2 citing K-001 into an empty bank is dropped, exactly as designed.

    Neither is routing by prompt. Phase 2, consolidation and promotion are all
    tool-less calls with different systems and different reply grammars, so one canned
    answer satisfies at most one of them and silently fails the rest. Answering the
    promotion call with Phase 2's grammar parses to no decisions, nothing is promoted,
    and this check would report an empty project bank as if the wiring were broken."""

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
            # A JSON array, and it has to be positive. This is the call that turns a
            # ticket's score into reinforcement on the entries its reminders cited,
            # and an entry with no reinforcement is never promoted. Answer it in the
            # wrong grammar and it parses to nothing, which is indistinguishable from
            # a run where the memory layer learned that its advice was worthless.
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
    """The customer says one thing, hears back, and leaves.

    It has to say something first, or the agent never takes a turn and this check
    passes having tested nothing. The turn count is read out of the conversation it
    was handed rather than kept in a counter here, because a counter is per process
    and this runs once per ticket."""
    prior = [m for m in messages if getattr(m, "role", "") != "system"]
    if len(prior) >= 2:
        return UserMessage(role="user", content="That is all, thanks. ###STOP###")
    return UserMessage(role="user", content="Hi, I need help with my task please.")


def main() -> int:
    # Each module bound `generate` at import, so each has to be replaced by name.
    # Missing one would send this check to a real endpoint.
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
            # advantage_enabled matters more than it looks and is off by default.
            # Reinforcement is applied inside the graded-session path, which only runs
            # when the advantage layer is on, and an entry with no reinforcement is
            # never promoted. Leave it off and the project bank stays empty forever
            # while every other signal looks healthy. run_live.py sets it for the
            # same reason.
            config=AgentMemConfig(
                state_dir=str(tmp / "mem"), advantage_enabled=True, advantage_gate=False
            ),
        )
    )
    name = register_agentmem_agent(run, name="agentmem-check")
    assert name in registry.get_agents(), "the agent never made it into tau2's registry"
    print(f"registered: {name}")
    print(f"agents tau2 now knows: {sorted(registry.get_agents())}")

    # Four, not one. An entry has to live through `continual_min_sessions_lived` (3)
    # sessions before it is promoted, so a single-ticket check would show an empty
    # project bank and prove nothing about whether tickets share anything.
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
    # Ticket by ticket, exactly as run_live does it for the memory arm, because the
    # reward has to be handed back before the next ticket starts.
    sims = []
    for task in tasks:
        try:
            sim = run_single_task(config, task, save_dir=tmp / "runs")
        except Exception as exc:
            print(f"  ticket {task.id}: {type(exc).__name__}: {exc}")
            continue
        sims.append(sim)
        reward = getattr(getattr(sim, "reward_info", None), "reward", 0.0) or 0.0
        # Forced to 1.0: the stub agent solves nothing, so every real reward is 0,
        # no entry is ever reinforced, and promotion could not fire no matter how
        # correct the wiring is. What is under test here is the path, not the score.
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

    # Not equal to the ticket count: tau2 retries a ticket that errors, and each retry
    # builds a fresh agent, which opens a fresh session. Worth knowing before reading
    # any session-count number off a real run.
    print(f"ticket boundaries the bank saw: {run.tickets_ended} (tickets that ran: {len(sims)})")
    assert run.tickets_ended == len(sims), "every ticket that ran should have ended exactly once"
    print(f"memory-model calls by kind: {sorted(set(mem_provider.calls))}")

    run.close()

    # The whole reason the memory arm exists here is that ticket N+1 opens a bank
    # ticket N wrote. If nothing was promoted, the arm is a per-ticket scratchpad
    # with extra steps, and it would still have passed every check above.
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
