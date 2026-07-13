"""The action agent: the thing being helped (or not) by memory.

The harness runs the same agent under every condition, so any difference in the
numbers comes from the memory wiring, not the agent.

  - ScriptedActionAgent: deterministic, no model. Runs the tests, and on failure
    either applies the real fix (if a reminder points at it) or repeats the wrong
    attempt. Makes the offline eval reproducible and free.
  - AnthropicActionAgent (live.py): a real terminal agent for live runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from agentmem.llm.base import LLMResponse
from agentmem.schemas import TokenUsage
from agentmem.tools import SAVE_PROCEDURAL, ToolCall

from .task import Task


@dataclass
class TurnObservation:
    command: str
    stdout: str
    exit_code: int

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class ActionAgent(Protocol):
    def start_session(self, task: Task) -> None: ...

    def act(self, task: Task, history: list[TurnObservation], reminder: str | None) -> str:
        """Return the next shell command, or "" to end the session."""
        ...

    @property
    def tokens(self) -> int: ...


class ScriptedActionAgent:
    """Runs the tests; on failure, takes the reminder's advice if it recognizes the
    fix, otherwise repeats the wrong attempt. No model, so `tokens` is always 0."""

    tokens = 0

    def start_session(self, task: Task) -> None:
        pass

    def act(self, task: Task, history: list[TurnObservation], reminder: str | None) -> str:
        offline = task.offline
        assert offline is not None, "ScriptedActionAgent needs an [offline] task script"

        last = history[-1] if history else None
        if last is None:
            return task.repo_test_command  # first move: see what's broken

        if last.command == task.repo_test_command:
            if last.ok:
                return ""  # tests pass, done
            if reminder and offline.recognize in reminder:
                return offline.fix_command  # the reminder pointed us at the real fix
            return offline.attempt_command  # flail: the tempting wrong edit

        return task.repo_test_command  # just edited something; re-run the tests


class ScriptedMemoryProvider:
    """A canned memory agent, parameterized per task. Records a diagnosis and, after
    the failure repeats, surfaces the task's hint. Reports zero tokens."""

    model = "scripted-eval"

    def __init__(self, hint: str) -> None:
        self._hint = hint
        self._phase1_calls = 0
        self._phase2_calls = 0

    def complete(self, *, system, messages, tools=None, max_tokens=1024):  # noqa: ANN001
        usage = TokenUsage(model=self.model)
        if tools:
            self._phase1_calls += 1
            # First step: a vague note. Second step: the real diagnosis (names the fix).
            content = self._hint if self._phase1_calls >= 2 else "tests failing; investigating"
            call = ToolCall(
                name=SAVE_PROCEDURAL,
                args={"id": "P-001", "tag": "diagnosis", "content": content},
                block_id="e1",
            )
            return LLMResponse(tool_calls=[call], usage=usage)

        self._phase2_calls += 1
        if self._phase2_calls < 2:
            return LLMResponse(text="<no_intervention/>", usage=usage)
        return LLMResponse(
            text=f"<context_for_action>\n- (P-001) {self._hint}\n</context_for_action>",
            usage=usage,
        )
