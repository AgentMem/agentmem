"""Run one (task, condition, seed) and produce a TaskResult."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from agentmem.schemas import Event

from .agent import ActionAgent, ScriptedActionAgent, ScriptedMemoryProvider, TurnObservation
from .budget import UsdBudget
from .conditions import build_strategy
from .metrics import TaskResult
from .task import Task

_COMMAND_TIMEOUT_S = 60
_SESSION_CONDITIONS = {"agentmem", "full_bank", "always_inject"}


def run_task(
    task: Task,
    condition: str,
    seed: int,
    *,
    offline: bool = True,
    memory_model: str = "claude-haiku-4-5",
    action_model: str | None = None,
    budget: UsdBudget | None = None,
) -> TaskResult:
    budget = budget or UsdBudget()

    with tempfile.TemporaryDirectory(prefix=f"agentmem-eval-{task.id}-") as tmp:
        workdir = Path(tmp) / "work"
        shutil.copytree(task.repo_dir, workdir)
        state_dir = Path(tmp) / "state"

        provider = (
            _memory_provider(task, offline, memory_model)
            if condition in _SESSION_CONDITIONS
            else None
        )
        strategy = build_strategy(condition, task, state_dir, provider)
        agent: ActionAgent = (
            ScriptedActionAgent() if offline else _live_agent(action_model or memory_model)
        )

        all_obs: list[TurnObservation] = []
        try:
            for _session in range(task.sessions):
                agent.start_session(task)
                history: list[TurnObservation] = []
                for _turn in range(task.max_turns):
                    reminder = strategy.context()
                    command = agent.act(task, history, reminder)
                    if not command:
                        break
                    obs = _run_command(command, workdir)
                    history.append(obs)
                    all_obs.append(obs)
                    strategy.observe(_events(obs))
                # Charge the memory tokens accrued so far; trips the cap on live runs.
                budget.charge(memory_model, strategy.memory_tokens, 0)
            passed = _verify(task, workdir)
            memory_steps = strategy.memory_steps
            memory_tokens = strategy.memory_tokens
            interventions = strategy.interventions
        finally:
            strategy.close()

        return TaskResult(
            task_id=task.id,
            condition=condition,
            seed=seed,
            passed=passed,
            repeated_failures=_repeated_failures(all_obs),
            requirement_violations=_requirement_violations(task, workdir),
            interventions=interventions,
            memory_steps=memory_steps,
            memory_tokens=memory_tokens,
            action_tokens=agent.tokens,
            turns=len(all_obs),
        )


def _run_command(command: str, workdir: Path) -> TurnObservation:
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(workdir),
            capture_output=True,
            text=True,
            timeout=_COMMAND_TIMEOUT_S,
        )
        out = (proc.stdout + proc.stderr).strip()
        return TurnObservation(command=command, stdout=out, exit_code=proc.returncode)
    except subprocess.TimeoutExpired:
        return TurnObservation(command=command, stdout="(timed out)", exit_code=124)


def _events(obs: TurnObservation) -> list[Event]:
    return [
        Event(kind="tool_call", tool_name="bash", text=obs.command),
        Event(kind="tool_result", tool_name="bash", ok=obs.ok, text=obs.stdout[-1500:]),
    ]


def _verify(task: Task, workdir: Path) -> bool:
    if task.verify_dir.is_dir():
        dst = workdir / "_verify"
        shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(task.verify_dir, dst)
        command = task.verify_command
    else:
        command = task.repo_test_command
    proc = subprocess.run(
        command,
        shell=True,
        cwd=str(workdir),
        capture_output=True,
        text=True,
        timeout=_COMMAND_TIMEOUT_S,
    )
    return proc.returncode == 0


def _requirement_violations(task: Task, workdir: Path) -> int:
    count = 0
    for fp in task.forbidden_patterns:
        path = workdir / fp.file
        if path.exists() and re.search(fp.pattern, path.read_text(encoding="utf-8")):
            count += 1
    return count


def _repeated_failures(observations: list[TurnObservation]) -> int:
    seen: set[str] = set()
    repeats = 0
    for obs in observations:
        if obs.exit_code == 0:
            continue
        key = re.sub(r"\s+", " ", obs.command.strip())
        if key in seen:
            repeats += 1
        seen.add(key)
    return repeats


def _memory_provider(task: Task, offline: bool, memory_model: str):  # noqa: ANN201
    if offline:
        hint = task.offline.memory_hint if task.offline else "investigate the failing test"
        return ScriptedMemoryProvider(hint)
    from agentmem.config import AgentMemConfig
    from agentmem.llm import make_provider

    return make_provider(AgentMemConfig(model=memory_model))


def _live_agent(model: str) -> ActionAgent:
    from .live import AnthropicActionAgent

    return AnthropicActionAgent(model=model)
