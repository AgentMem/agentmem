"""A tau2-bench agent that is tau2's own agent plus a memory layer, and nothing else.

The baseline arm runs tau2's `llm_agent` unmodified. This arm subclasses it and
overrides two methods. Everything the two arms share, they share by inheritance
rather than by being written twice, so a difference in the results cannot come
from a difference in the harness.
"""

from __future__ import annotations

import json
from typing import Any

from agentmem.session import MemorySession

try:
    from tau2.agent.llm_agent import LLMAgent
    from tau2.data_model.message import (
        MultiToolMessage,
        SystemMessage,
        ToolMessage,
        UserMessage,
    )

    _HAVE_TAU2 = True
except ModuleNotFoundError:  # importable from our venv, runnable only where tau2 is
    LLMAgent = object  # type: ignore[assignment,misc]
    SystemMessage = None  # type: ignore[assignment]
    _HAVE_TAU2 = False


def have_tau2() -> bool:
    return _HAVE_TAU2


# Said plainly, because the agent is about to read this next to a real customer's
# words and must not confuse the two.
REMINDER_PREFIX = (
    "Note from your own memory of earlier tickets. The customer did not say this. "
    "Each line cites the note it came from."
)


class AgentMemLLMAgent(LLMAgent):  # type: ignore[misc]
    """tau2's LLMAgent, with a memory layer watching and occasionally interrupting.

    Two overrides, both deliberate:

    `_generate_next_message` slips a reminder in for exactly one call. It is appended
    to `state.messages` before the parent runs and removed in a `finally`, so it
    reaches the model while it is deciding and is gone before anything is saved. That
    matters here more than it does in the terminal eval: tau2 grades the trajectory,
    so a reminder left behind would become a message the agent never received.

    What it deliberately does not do is end the session in `stop`. tau2 scores a
    ticket after the conversation is over, so an agent being told to stop does not yet
    know whether it succeeded, and ending the ticket with a neutral reward there costs
    more than it looks: a graded reward of zero moves no reinforcement, an entry with
    no reinforcement is never eligible for promotion, and the project bank stays empty
    for the whole run. The ticket boundary belongs to the runner, which has the
    verdict. See MemoryRun.end_ticket.
    """

    def __init__(
        self,
        tools: list,
        domain_policy: str,
        llm: str,
        llm_args: dict | None = None,
        *,
        memory: MemorySession | None = None,
    ) -> None:
        super().__init__(tools=tools, domain_policy=domain_policy, llm=llm, llm_args=llm_args)
        self._memory = memory
        self.reminders_injected = 0

    def _generate_next_message(self, message: Any, state: Any) -> Any:
        if self._memory is None:
            return super()._generate_next_message(message, state)

        self._observe_input(message)
        reminder = self._memory.pending_context()
        if not reminder:
            reply = super()._generate_next_message(message, state)
            self._observe_output(reply)
            return reply

        note = SystemMessage(role="system", content=f"{REMINDER_PREFIX}\n{reminder}")
        state.messages.append(note)
        try:
            reply = super()._generate_next_message(message, state)
        finally:
            # By identity: two identical reminders must not collapse into one removal.
            state.messages[:] = [m for m in state.messages if m is not note]
        self.reminders_injected += 1
        self._observe_output(reply)
        return reply

    def stop(self, message: Any = None, state: Any = None) -> None:
        # Intentionally leaves the memory alone; the runner ends the ticket once it
        # knows the score. Closing or ending here would spend the boundary on a
        # reward nobody has computed yet.
        super().stop(message, state)

    def _observe_input(self, message: Any) -> None:
        events = []
        if isinstance(message, MultiToolMessage):
            for tm in message.tool_messages:
                events.append(_tool_result_event(tm))
        elif isinstance(message, ToolMessage):
            events.append(_tool_result_event(message))
        elif isinstance(message, UserMessage):
            events.append(
                {"kind": "message", "role": "user", "text": (message.content or "")[:2000]}
            )
        if events:
            self._memory.observe(events)  # type: ignore[union-attr]

    def _observe_output(self, reply: Any) -> None:
        events: list[dict[str, Any]] = []
        if getattr(reply, "tool_calls", None):
            for tc in reply.tool_calls:
                events.append(
                    {
                        "kind": "tool_call",
                        "tool_name": tc.name,
                        "text": json.dumps(tc.arguments, default=str)[:500],
                    }
                )
        if getattr(reply, "content", None):
            events.append(
                {"kind": "message", "role": "assistant", "text": (reply.content or "")[:1000]}
            )
        if events:
            self._memory.observe(events)  # type: ignore[union-attr]


def _tool_result_event(tm: Any) -> dict[str, Any]:
    return {
        "kind": "tool_result",
        "tool_name": getattr(tm, "id", "") or "tool",
        "ok": not getattr(tm, "error", False),
        "text": (getattr(tm, "content", "") or "")[:1500],
    }


class MemoryRun:
    """One session for the whole run, ended once per ticket. Not one per ticket.

    This is the part that is easy to get backwards, and getting it backwards costs
    nothing visible: the agent still injects, the reminders are still grounded, every
    ticket still works, and the project bank stays empty forever.

    Promotion is what lets ticket N+1 use what ticket N learned, and an entry only
    becomes eligible once `bank.sessions_seen - entry.created_session` reaches
    `continual_min_sessions_lived`. That counter lives on the bank and is advanced by
    `end_session`. Give each ticket its own MemorySession and each ticket gets its own
    bank, whose counter starts at zero and is thrown away at the end, so nothing is
    ever eligible and the arm quietly degrades into a per-ticket scratchpad.

    One session with a ticket boundary at each `end_session` is the shape the
    lifecycle was built for, and the shape the daemon already uses across many
    Claude Code sessions.

    Tickets therefore run in order, one at a time. Two at once would interleave two
    conversations into one bank; the runner keeps tau2's concurrency at 1 for this
    arm and puts the parallelism in separate shards, each with its own state dir.
    """

    def __init__(self, session: MemorySession) -> None:
        self._session = session
        self._closed = False

    @property
    def session(self) -> MemorySession:
        return self._session

    @property
    def tickets_ended(self) -> int:
        """Ticket boundaries the bank has seen. Promotion counts against this."""
        return self._session.bank.sessions_seen

    def end_ticket(self, reward: float) -> None:
        """Call this once per ticket, with what the ticket actually scored.

        The reward is not bookkeeping. It is what reinforces the entries the reminders
        cited, and only a reinforced entry is ever promoted, so a run that ends every
        ticket at 0.0 will look completely healthy and never build a project bank.
        tau2 scores rewards in [0, 1] and the memory layer wants [-1, +1], hence the
        rescale: a ticket that failed should push its notes down, not merely fail to
        push them up."""
        self._session.end_session(task_reward=(reward * 2.0) - 1.0)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._session.close(task_reward=0.0)


def register_agentmem_agent(
    run: MemoryRun,
    name: str = "agentmem",
    registry: Any = None,
) -> str:
    """Add the agent to tau2's registry from out here, rather than by editing tau2.

    tau2 has no plugin hook, but its registry is a plain importable object, so the
    vendored checkout stays exactly as upstream published it and there is nothing to
    re-apply when it moves.

    The factory has to accept every keyword tau2 passes (`task`, `audio_native_config`,
    `audio_taps_dir`, ...) and quietly drop the ones it does not use.
    """
    if registry is None:
        from tau2.registry import registry as _registry

        registry = _registry

    def factory(tools: list, domain_policy: str, **kwargs: Any) -> AgentMemLLMAgent:
        # tau2 builds a new agent per ticket, and per retry of a ticket. They all get
        # the same session: the bank is the thing that is supposed to outlive them.
        return AgentMemLLMAgent(
            tools=tools,
            domain_policy=domain_policy,
            llm=kwargs.get("llm"),
            llm_args=kwargs.get("llm_args"),
            memory=run.session,
        )

    registry.register_agent_factory(factory, name)
    return name
