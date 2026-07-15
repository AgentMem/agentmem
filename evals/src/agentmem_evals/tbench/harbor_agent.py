"""harbor shim around ActionLoop; see evals/tbench/README.md for how to run it."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentmem import __version__ as agentmem_version
from agentmem.config import AgentMemConfig
from agentmem.llm.base import LLMProvider
from agentmem.session import MemorySession
from agentmem.triggers import default

from .loop import ActionLoop, CountingProvider, Decision


def build_provider(
    model: str, *, api_base: str = "", timeout: float = 300.0, no_thinking: bool = False
) -> LLMProvider:
    """Anthropic by default; a `litellm/` prefix routes anywhere else, including a
    vLLM or Ollama server you run yourself.

    The 300s timeout is deliberate: the library default is 30s, sized for quick
    memory-step calls, and a thinking model working a long task instruction blows
    past it on the first request and kills the trial at turn zero. no_thinking asks
    a vLLM chat template to drop the reasoning trace, which for a heavy thinker like
    Qwen3.6 is the difference between a snappy tool call and a per-turn timeout."""
    if model.startswith("litellm/"):
        from agentmem.llm.litellm import LiteLLMProvider

        return LiteLLMProvider(
            model=model.removeprefix("litellm/"),
            api_base=api_base or None,
            timeout=timeout,
            extra_body=(
                {"chat_template_kwargs": {"enable_thinking": False}} if no_thinking else None
            ),
        )
    from agentmem.llm.anthropic import AnthropicProvider

    return AnthropicProvider(model=model, timeout=timeout)


try:
    from harbor.agents.base import BaseAgent

    _HAVE_HARBOR = True
except ModuleNotFoundError:  # workspace venv: importable, not runnable
    BaseAgent = object  # type: ignore[assignment,misc]
    _HAVE_HARBOR = False

if TYPE_CHECKING:
    from harbor.environments.base import BaseEnvironment
    from harbor.models.agent.context import AgentContext


class AgentMemTerminalAgent(BaseAgent):  # type: ignore[misc]
    """One agent, two arms. arm=baseline runs the plain loop; arm=memory attaches a
    fresh per-trial MemorySession whose reminders land in the next turn."""

    def __init__(
        self,
        *args: Any,
        arm: str = "baseline",
        action_model: str = "claude-haiku-4-5",
        memory_model: str = "",
        max_turns: str = "30",
        task_usd_cap: str = "0.25",
        exec_timeout_sec: str = "120",
        max_tokens: str = "1024",
        api_base: str = "",
        no_thinking: str = "false",
        **kwargs: Any,
    ) -> None:
        if not _HAVE_HARBOR:
            raise ImportError(
                "harbor isn't installed in this environment. "
                "Run this agent from the eval venv (see evals/tbench/README.md)."
            )
        super().__init__(*args, **kwargs)
        if arm not in ("baseline", "memory"):
            raise ValueError(f"arm must be baseline or memory, got {arm!r}")
        self._arm = arm
        self._action_model = action_model
        self._memory_model = memory_model or action_model
        self._max_turns = int(max_turns)
        self._task_usd_cap = float(task_usd_cap)
        self._exec_timeout_sec = int(exec_timeout_sec)
        # Models with adaptive thinking (Sonnet 5 and up) need real output headroom.
        self._max_tokens = int(max_tokens)
        self._api_base = api_base
        self._no_thinking = str(no_thinking).lower() in ("1", "true", "yes")

    @staticmethod
    def name() -> str:
        return "agentmem-terminal"

    def version(self) -> str | None:
        return agentmem_version

    async def setup(self, environment: BaseEnvironment) -> None:
        return None

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        action = CountingProvider(
            build_provider(
                self._action_model, api_base=self._api_base, no_thinking=self._no_thinking
            )
        )
        memory: MemorySession | None = None
        mem_provider: CountingProvider | None = None
        if self._arm == "memory":
            mem_provider = CountingProvider(
                build_provider(
                    self._memory_model, api_base=self._api_base, no_thinking=self._no_thinking
                )
            )
            memory = MemorySession(
                task=instruction[:400],
                provider=mem_provider,
                trigger=default(),
                async_worker=False,
                # Record decisions for offline analysis. The gate stays off and the
                # per-trial store starts empty, so recording can't change behavior.
                config=AgentMemConfig(
                    state_dir=str(Path(self.logs_dir) / "agentmem"),
                    advantage_enabled=True,
                    advantage_gate=False,
                ),
            )

        loop = ActionLoop(
            action,
            instruction,
            memory=memory,
            extra_cost=(lambda: mem_provider.usd) if mem_provider is not None else None,
            max_turns=self._max_turns,
            usd_cap=self._task_usd_cap,
            max_tokens=self._max_tokens,
        )

        try:
            while True:
                decision = await asyncio.to_thread(loop.next_decision)
                if decision.kind != "exec":
                    break
                started = time.monotonic()
                result = await environment.exec(
                    command=decision.command,
                    timeout_sec=min(decision.timeout_sec, self._exec_timeout_sec),
                )
                await asyncio.to_thread(
                    loop.record_exec,
                    decision,
                    result.stdout or "",
                    result.stderr or "",
                    result.return_code,
                    time.monotonic() - started,
                )
                self._fill_context(context, loop, action, mem_provider)
        finally:
            await asyncio.to_thread(loop.close)
            self._fill_context(context, loop, action, mem_provider)
            self._dump_logs(loop)

    def _fill_context(
        self,
        context: AgentContext,
        loop: ActionLoop,
        action: CountingProvider,
        mem_provider: CountingProvider | None,
    ) -> None:
        mem_in = mem_provider.input_tokens if mem_provider else 0
        mem_out = mem_provider.output_tokens if mem_provider else 0
        mem_usd = mem_provider.usd if mem_provider else 0.0
        context.n_input_tokens = action.input_tokens + mem_in
        context.n_output_tokens = action.output_tokens + mem_out
        context.cost_usd = round(loop.spent_usd + mem_usd, 6)
        context.metadata = {
            "arm": self._arm,
            "action_model": self._action_model,
            "memory_model": self._memory_model if self._arm == "memory" else None,
            "turns": loop.turns,
            "stop_reason": loop.stop_reason,
            "reminders_injected": loop.reminders_injected,
            "action_usd": round(loop.spent_usd, 6),
            "memory_usd": round(mem_usd, 6),
        }

    def _dump_logs(self, loop: ActionLoop) -> None:
        logs = Path(self.logs_dir)
        logs.mkdir(parents=True, exist_ok=True)
        with (logs / "loop_transcript.jsonl").open("w") as fh:
            for entry in loop.transcript:
                fh.write(json.dumps(entry) + "\n")


__all__ = ["AgentMemTerminalAgent", "Decision"]
