"""The tau2 adapter, tested without tau2, a GPU, a key, or a network.

tau2 needs Python >=3.12 and this suite runs on 3.11, so when it is absent these
tests stand up a double of the two tau2 pieces the adapter touches. The double is
copied from tau2's own `LLMAgent._generate_next_message`, which makes it a
restatement of upstream's behaviour and therefore able to drift from it. The check
against that is `evals/tau2/check_adapter.py`, which runs this same adapter against
the real classes in the tau2 venv. When tau2 does happen to be importable, the
fixture below hands over the real thing and these tests become the real check.
"""

from __future__ import annotations

import importlib
import sys
import types

import pytest
from agentmem.config import AgentMemConfig
from agentmem.llm.base import LLMResponse
from agentmem.schemas import TokenUsage
from agentmem.session import MemorySession
from agentmem.triggers import every_n

_USAGE = TokenUsage(input_tokens=10, output_tokens=5, model="scripted")


class _Scripted:
    """Phase 1 carries tools, Phase 2 does not; both stay silent once the script runs
    out, which is the safe default and what an exhausted script should mean."""

    model = "scripted"

    def __init__(self, phase2: list[str] | None = None) -> None:
        self._phase2 = list(phase2 or [])
        self.calls = 0

    def complete(self, *, system, messages, tools=None, max_tokens=1024):  # noqa: ANN001
        self.calls += 1
        if tools:
            return LLMResponse(usage=_USAGE)
        text = self._phase2.pop(0) if self._phase2 else "<no_intervention/>"
        return LLMResponse(text=text, usage=_USAGE)


def _fake_tau2() -> dict[str, types.ModuleType]:
    """The smallest tau2 the adapter can be judged against."""
    import dataclasses

    @dataclasses.dataclass
    class SystemMessage:
        role: str = "system"
        content: str | None = None

    @dataclasses.dataclass
    class UserMessage:
        role: str = "user"
        content: str | None = None
        tool_calls: list | None = None
        is_audio: bool = False

        def is_tool_call(self) -> bool:
            return bool(self.tool_calls)

    @dataclasses.dataclass
    class AssistantMessage:
        role: str = "assistant"
        content: str | None = None
        tool_calls: list | None = None

        def is_tool_call(self) -> bool:
            return bool(self.tool_calls)

    @dataclasses.dataclass
    class ToolMessage:
        id: str = "t1"
        role: str = "tool"
        content: str | None = None
        requestor: str = "assistant"
        error: bool = False

    @dataclasses.dataclass
    class MultiToolMessage:
        role: str = "tool"
        tool_messages: list = dataclasses.field(default_factory=list)

    msg_mod = types.ModuleType("tau2.data_model.message")
    for cls in (
        SystemMessage,
        UserMessage,
        AssistantMessage,
        ToolMessage,
        MultiToolMessage,
    ):
        setattr(msg_mod, cls.__name__, cls)

    agent_mod = types.ModuleType("tau2.agent.llm_agent")

    class LLMAgent:
        """A restatement of tau2's LLMAgent, down to reaching `generate` through the
        module globals, which is what lets one stub serve both this and the real one."""

        def __init__(self, tools, domain_policy, llm, llm_args=None):
            self.tools = tools
            self.domain_policy = domain_policy
            self.llm = llm
            self.llm_args = llm_args or {}

        def _generate_next_message(self, message, state):
            if isinstance(message, MultiToolMessage):
                state.messages.extend(message.tool_messages)
            else:
                state.messages.append(message)
            messages = state.system_messages + state.messages
            return agent_mod.generate(
                model=self.llm,
                tools=self.tools,
                messages=messages,
                call_name="agent_response",
                **self.llm_args,
            )

        def stop(self, message=None, state=None) -> None:
            return None

    agent_mod.LLMAgent = LLMAgent
    agent_mod.generate = None  # the test installs one; a real call must never happen

    tau2 = types.ModuleType("tau2")
    tau2_agent = types.ModuleType("tau2.agent")
    tau2_dm = types.ModuleType("tau2.data_model")
    return {
        "tau2": tau2,
        "tau2.agent": tau2_agent,
        "tau2.agent.llm_agent": agent_mod,
        "tau2.data_model": tau2_dm,
        "tau2.data_model.message": msg_mod,
    }


class _Sent:
    """Records every message list handed to the model, so a test can ask what the
    model actually saw rather than trusting that the injection happened."""

    def __init__(self) -> None:
        self.windows: list[list] = []

    def install(self, monkeypatch, msg_mod):
        def generate(*, model, messages, tools=None, call_name=None, **kwargs):
            self.windows.append(list(messages))
            return msg_mod.AssistantMessage(role="assistant", content="ok")

        monkeypatch.setattr(sys.modules["tau2.agent.llm_agent"], "generate", generate)
        return self

    @property
    def last_text(self) -> str:
        return " ".join(str(getattr(m, "content", "") or "") for m in self.windows[-1])


@pytest.fixture
def tau2mod(monkeypatch):
    """The adapter module, bound to real tau2 when it is importable and to the double
    when it is not. Either way `generate` is stubbed, so no test can reach a network."""
    try:
        import tau2.agent.llm_agent  # noqa: F401

        real = True
    except ModuleNotFoundError:
        real = False
        for name, mod in _fake_tau2().items():
            monkeypatch.setitem(sys.modules, name, mod)
    mod = importlib.reload(importlib.import_module("agentmem_evals.tau2.agent"))
    mod.REAL_TAU2 = real
    mod.sent = _Sent().install(monkeypatch, sys.modules["tau2.data_model.message"])
    yield mod
    monkeypatch.undo()
    importlib.reload(importlib.import_module("agentmem_evals.tau2.agent"))


def _state(tau2mod):
    msg = sys.modules["tau2.data_model.message"]
    return types.SimpleNamespace(
        system_messages=[msg.SystemMessage(role="system", content="policy")],
        messages=[],
    )


def _user(text: str):
    """role is required on the real models and defaulted on the double; always pass it."""
    return sys.modules["tau2.data_model.message"].UserMessage(role="user", content=text)


def _memory(tmp_path, replies: list[str] | None = None) -> MemorySession:
    return MemorySession(
        task="handle tickets",
        provider=_Scripted(replies),
        trigger=every_n(1),
        async_worker=False,
        session_id="s1",
        config=AgentMemConfig(state_dir=str(tmp_path / "mem")),
    )


def test_without_memory_the_adapter_is_exactly_tau2s_agent(tau2mod, tmp_path):
    """The baseline arm must not be a different agent wearing our name."""
    agent = tau2mod.AgentMemLLMAgent(tools=[], domain_policy="p", llm="m", memory=None)
    state = _state(tau2mod)
    agent._generate_next_message(_user("hi"), state)

    assert [type(m).__name__ for m in state.messages] == ["UserMessage"]
    assert tau2mod.REMINDER_PREFIX not in tau2mod.sent.last_text
    assert agent.reminders_injected == 0


def test_reminder_reaches_the_model_and_leaves_no_trace(tau2mod, tmp_path):
    """The whole point of the override: the model sees it, the record does not."""
    memory = _memory(tmp_path, [])
    memory._pending = "- watch the fare rules (K-001)"

    agent = tau2mod.AgentMemLLMAgent(tools=[], domain_policy="p", llm="m", memory=memory)
    state = _state(tau2mod)
    agent._generate_next_message(_user("cancel my flight"), state)

    assert "fare rules (K-001)" in tau2mod.sent.last_text, "the reminder never reached the model"
    assert tau2mod.REMINDER_PREFIX in tau2mod.sent.last_text

    left = [m for m in state.messages if type(m).__name__ == "SystemMessage"]
    assert left == [], "a reminder was left behind in the trajectory tau2 grades"
    assert agent.reminders_injected == 1
    memory.close()


def test_reminder_lands_next_to_the_turn_it_is_for(tau2mod, tmp_path):
    """Ahead of the customer's latest line, not buried at the top of the context."""
    memory = _memory(tmp_path, [])
    memory._pending = "- check fare rules (K-001)"
    agent = tau2mod.AgentMemLLMAgent(tools=[], domain_policy="p", llm="m", memory=memory)
    state = _state(tau2mod)
    agent._generate_next_message(_user("cancel my flight"), state)

    roles = [getattr(m, "role", "") for m in tau2mod.sent.windows[-1]]
    assert roles[-1] == "user", "the customer's turn must stay last"
    assert roles[-2] == "system", "the reminder should sit immediately before it"
    memory.close()


def test_identical_reminders_do_not_collapse(tau2mod, tmp_path):
    """Removal is by identity; equality would delete the wrong message."""
    msg = sys.modules["tau2.data_model.message"]
    memory = _memory(tmp_path, [])
    agent = tau2mod.AgentMemLLMAgent(tools=[], domain_policy="p", llm="m", memory=memory)
    state = _state(tau2mod)
    twin = msg.SystemMessage(role="system", content=f"{tau2mod.REMINDER_PREFIX}\n- x (K-001)")
    state.messages.append(twin)

    memory._pending = "- x (K-001)"
    agent._generate_next_message(_user("hi"), state)

    assert any(m is twin for m in state.messages), "an identical earlier message was removed"
    memory.close()


def test_silence_injects_nothing(tau2mod, tmp_path):
    memory = _memory(tmp_path, [])
    agent = tau2mod.AgentMemLLMAgent(tools=[], domain_policy="p", llm="m", memory=memory)
    state = _state(tau2mod)
    agent._generate_next_message(_user("hi"), state)

    assert agent.reminders_injected == 0
    assert tau2mod.REMINDER_PREFIX not in tau2mod.sent.last_text
    assert [m for m in state.messages if type(m).__name__ == "SystemMessage"] == []
    memory.close()


def test_tool_results_and_calls_reach_memory(tau2mod, tmp_path):
    msg = sys.modules["tau2.data_model.message"]
    memory = _memory(tmp_path, [])
    agent = tau2mod.AgentMemLLMAgent(tools=[], domain_policy="p", llm="m", memory=memory)
    state = _state(tau2mod)

    multi = msg.MultiToolMessage(
        role="tool",
        tool_messages=[
            msg.ToolMessage(
                id="get_reservation", role="tool", content="RES123", requestor="assistant"
            ),
            msg.ToolMessage(
                id="get_fare", role="tool", content="boom", requestor="assistant", error=True
            ),
        ],
    )
    agent._generate_next_message(multi, state)

    kinds = [e.kind for e in memory._history]
    assert kinds.count("tool_result") == 2, "both tool results should reach the bank"
    texts = " ".join(e.text for e in memory._history)
    assert "RES123" in texts and "boom" in texts
    memory.close()


def test_stop_leaves_the_ticket_boundary_to_the_runner(tau2mod, tmp_path):
    """stop must not end the ticket. tau2 scores a ticket after the conversation is
    over, so an agent ending it here can only pass a reward of zero, a zero reward
    moves no reinforcement, and an entry with no reinforcement is never promoted. The
    project bank would stay empty for the whole run with nothing looking wrong."""
    memory = _memory(tmp_path)
    agent = tau2mod.AgentMemLLMAgent(tools=[], domain_policy="p", llm="m", memory=memory)
    before = memory.bank.sessions_seen

    agent.stop(None, None)
    agent.stop(None, None)  # tau2 calls it on the normal and the error path

    assert memory.bank.sessions_seen == before, "stop spent a ticket boundary"
    memory.close()


def test_end_ticket_advances_the_counter_promotion_reads(tau2mod, tmp_path):
    memory = _memory(tmp_path)
    run = tau2mod.MemoryRun(memory)
    assert run.tickets_ended == 0

    run.end_ticket(1.0)
    run.end_ticket(0.0)

    assert run.tickets_ended == 2
    run.close()
    run.close()  # idempotent


def test_a_failed_ticket_pushes_its_notes_down_not_merely_not_up(tau2mod, tmp_path):
    """tau2 rewards land in [0, 1] and the memory layer wants [-1, 1]. Passing the raw
    reward through would make a failed ticket read as neutral, so bad advice would
    never be marked as bad."""
    seen: list[float] = []
    memory = _memory(tmp_path)
    memory.end_session = lambda task_reward=0.0: seen.append(task_reward)  # type: ignore[method-assign]
    run = tau2mod.MemoryRun(memory)

    run.end_ticket(1.0)
    run.end_ticket(0.0)
    run.end_ticket(0.5)

    assert seen == [1.0, -1.0, 0.0]


def test_every_agent_in_a_run_shares_one_session(tau2mod, tmp_path):
    """tau2 builds an agent per ticket and per retry. They must all get the same bank:
    a session per ticket restarts the counter promotion reads, so nothing is ever
    eligible and the arm silently becomes a per-ticket scratchpad."""

    class Reg:
        def __init__(self) -> None:
            self.factories: dict = {}

        def register_agent_factory(self, factory, name, **kw):
            self.factories[name] = factory

    memory = _memory(tmp_path)
    run = tau2mod.MemoryRun(memory)
    reg = Reg()
    tau2mod.register_agentmem_agent(run, name="agentmem", registry=reg)

    first = reg.factories["agentmem"](tools=[], domain_policy="p", llm="m", task=None)
    second = reg.factories["agentmem"](tools=[], domain_policy="p", llm="m", task=None)

    assert first._memory is second._memory is memory
    run.close()


def test_factory_registers_and_builds_through_a_fake_registry(tau2mod, tmp_path):
    """Registration must work from out here, so the tau2 checkout stays untouched."""

    class Reg:
        def __init__(self) -> None:
            self.factories: dict = {}

        def register_agent_factory(self, factory, name, **kw):
            self.factories[name] = factory

    run = tau2mod.MemoryRun(_memory(tmp_path))
    reg = Reg()
    name = tau2mod.register_agentmem_agent(run, name="agentmem", registry=reg)
    assert name in reg.factories

    # tau2 calls the factory with all of these; swallowing them is the contract.
    agent = reg.factories[name](
        tools=[],
        domain_policy="p",
        llm="m",
        llm_args={"api_base": "http://x/v1"},
        task=types.SimpleNamespace(id="task-9"),
        audio_native_config=None,
        audio_taps_dir=None,
    )
    assert agent._memory is not None
    assert agent.llm_args == {"api_base": "http://x/v1"}, "llm_args must reach tau2's generate"
    run.close()
