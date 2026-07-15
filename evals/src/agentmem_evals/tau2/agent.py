"""tau2's own llm_agent with a memory layer bolted on, and nothing else different.

The baseline arm runs the parent unmodified, so the two arms cannot differ by
anything except the memory.
"""

from __future__ import annotations

import json
from typing import Any

from agentmem.session import MemorySession

try:
    from tau2.agent.llm_agent import LLMAgent
    from tau2.data_model.message import (
        MultiToolMessage,
        ToolMessage,
        UserMessage,
    )

    _HAVE_TAU2 = True
except ModuleNotFoundError:  # importable from our venv, runnable only where tau2 is
    LLMAgent = object  # type: ignore[assignment,misc]
    UserMessage = None  # type: ignore[assignment]
    _HAVE_TAU2 = False


def have_tau2() -> bool:
    return _HAVE_TAU2


# The agent reads this next to a real customer's words, so it says whose words it is.
REMINDER_PREFIX = (
    "Note from your own memory of earlier tickets. The customer did not say this. "
    "Each line cites the note it came from."
)


class AgentMemLLMAgent(LLMAgent):  # type: ignore[misc]
    """A reminder rides along for one call and is gone before the state is saved.

    tau2 grades the trajectory, so anything left in it becomes a message the agent
    was never sent. `stop` deliberately leaves the memory alone: the ticket boundary
    belongs to whoever knows the score, which is the runner. See MemoryRun.
    """

    def __init__(
        self,
        tools: list[Any],
        domain_policy: str,
        llm: str,
        llm_args: dict[str, Any] | None = None,
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

        # A user turn, not a system one: Qwen3.6's template 400s on a system message
        # anywhere but the front. The prefix carries the provenance instead.
        note = UserMessage(role="user", content=f"{REMINDER_PREFIX}\n{reminder}")
        state.messages.append(note)
        try:
            reply = super()._generate_next_message(message, state)
        finally:
            # By identity; two identical reminders must not collapse into one removal.
            state.messages[:] = [m for m in state.messages if m is not note]
        self.reminders_injected += 1
        self._observe_output(reply)
        return reply

    def stop(self, message: Any = None, state: Any = None) -> None:
        super().stop(message, state)  # the runner ends the ticket, once it has the score

    def _observe_input(self, message: Any) -> None:
        events: list[dict[str, Any]] = []
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
    """One session for the whole run, ended once per ticket. Not one session per ticket.

    Promotion needs an entry to outlive `continual_min_sessions_lived` boundaries on
    its bank, and that counter dies with the session. A session per ticket therefore
    never promotes anything, silently: every ticket still works and the project bank
    stays empty. One bank also means one ticket at a time.
    """

    def __init__(self, session: MemorySession) -> None:
        self._session = session
        self._closed = False

    @property
    def session(self) -> MemorySession:
        return self._session

    @property
    def tickets_ended(self) -> int:
        """Boundaries the bank has seen. Promotion counts against this."""
        return self._session.bank.sessions_seen

    def end_ticket(self, reward: float) -> None:
        """Once per ticket, with the score it got. The reward reinforces the entries
        its reminders cited, and only a reinforced entry is ever promoted, so ending
        every ticket at zero builds nothing. tau2 scores [0, 1]; memory wants [-1, 1],
        so a failed ticket pushes its notes down rather than merely not up."""
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
    """Register from out here so the vendored tau2 checkout stays as upstream shipped it.

    There is no plugin hook, but the registry is a plain importable object. The factory
    must swallow every keyword tau2 passes, including the ones it ignores.
    """
    if registry is None:
        from tau2.registry import registry as _registry

        registry = _registry

    def factory(tools: list[Any], domain_policy: str, **kwargs: Any) -> AgentMemLLMAgent:
        llm = kwargs.get("llm")
        if not llm:
            raise ValueError("no llm reached the factory; tau2 takes it from config.llm_agent")
        # A new agent per ticket and per retry; they all share the bank that outlives them.
        return AgentMemLLMAgent(
            tools=tools,
            domain_policy=domain_policy,
            llm=llm,
            llm_args=kwargs.get("llm_args"),
            memory=run.session,
        )

    registry.register_agent_factory(factory, name)
    return name
