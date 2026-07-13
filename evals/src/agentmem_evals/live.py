"""A real terminal agent for live eval runs.

Deliberately simple: the model replies with exactly one shell command per turn (or
DONE), we run it, and feed the output back as plain text. No tool-use protocol to get
subtly wrong. Needs ANTHROPIC_API_KEY; it is not exercised by the offline test suite,
so treat it as the part to validate first on a real run.
"""

from __future__ import annotations

from .agent import TurnObservation
from .task import Task

_SYSTEM = """You are fixing a bug in a code repository by running shell commands, one \
per turn. After each command you'll see its output. Reply with EXACTLY one shell \
command to run next — no markdown, no explanation — or the single word DONE once the \
tests pass. Respect any constraints stated in the task."""


class AnthropicActionAgent:
    def __init__(self, model: str, api_key: str | None = None) -> None:
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.tokens = 0
        self._messages: list[dict] = []

    def start_session(self, task: Task) -> None:
        self._messages = [{"role": "user", "content": _intro(task)}]

    def act(self, task: Task, history: list[TurnObservation], reminder: str | None) -> str:
        if history:
            last = history[-1]
            content = f"$ {last.command}\nexit={last.exit_code}\n{last.stdout[-2000:]}"
            if reminder:
                content = f"{reminder}\n\n{content}"
            self._messages.append({"role": "user", "content": content})

        resp = self._client.messages.create(
            model=self.model, system=_SYSTEM, messages=self._messages, max_tokens=400
        )
        self.tokens += resp.usage.input_tokens + resp.usage.output_tokens
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        self._messages.append({"role": "assistant", "content": text})

        if not text or text.upper().startswith("DONE"):
            return ""
        return _first_command(text)


def _intro(task: Task) -> str:
    lines = [task.description, "", f"Run the tests with: {task.repo_test_command}"]
    if task.requirements:
        lines.append("Constraints:")
        lines += [f"- {r}" for r in task.requirements]
    lines.append("\nWhat is your first command?")
    return "\n".join(lines)


def _first_command(text: str) -> str:
    for raw in text.splitlines():
        line = raw.strip().strip("`").strip()
        if line.startswith("$ "):
            line = line[2:].strip()
        if line:
            return line
    return ""
