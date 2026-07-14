"""Grade each memory-step after the fact."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ..llm.base import LLMProvider

OUTCOME_EVALUATOR_SYSTEM = """\
You are the Outcome Evaluator for a memory agent that assists a long-horizon coding \
agent. You are given the TASK, the full TRAJECTORY, the final TASK RESULT (verifier \
pass/fail if available), and the list of MEMORY STEPS, each with its step index, the \
bank edits it made, and its decision (silent, or the injected reminder text).

For EACH memory step output one JSON object:
{"step": <int>, "reward": <float in [-1,1]>, "label": "<one of: changed_behavior_good \
| prevented_repeat | silent_correct | silent_missed | redundant_reminder | \
harmful_reminder | no_effect>", "why": "<one short sentence citing turn numbers>"}

Scoring guide:
 +0.8..1.0  a reminder that clearly changed the next 1-2 actions for the better \
(avoided a stored failed attempt, enforced a requirement, applied a stored diagnosis), \
or silence while the agent was on track and a reminder would only have added noise.
 +0.2..0.5  a plausible positive effect with weak evidence.
  0.0       no observable effect.
 -0.2..-0.5 a redundant reminder (restated visible info, or repeated within cooldown), \
or silence right before the agent repeated a failure that was in the bank.
 -0.6..-1.0 a reminder that misled the agent or preceded a requirement violation.

Judge only from the trajectory. Do not reward verbosity. Output a JSON array and \
nothing else."""


@dataclass
class StepSummary:
    step: int
    edits: str  # e.g. "created K-004, updated P-001"
    decision: str  # "silent" or the injected reminder text


@dataclass
class StepEval:
    step: int
    reward: float
    label: str
    why: str


def evaluate(
    provider: LLMProvider,
    *,
    task: str,
    trajectory: str,
    task_result: str,
    steps: list[StepSummary],
    max_tokens: int = 1024,
) -> list[StepEval]:
    if not steps:
        return []
    user = "\n\n".join(
        [
            f"TASK:\n{task}",
            f"TASK RESULT:\n{task_result}",
            f"TRAJECTORY:\n{trajectory}",
            "MEMORY STEPS:\n"
            + "\n".join(f"- step {s.step}: edits=[{s.edits}] decision={s.decision}" for s in steps),
        ]
    )
    resp = provider.complete(
        system=OUTCOME_EVALUATOR_SYSTEM,
        messages=[{"role": "user", "content": user}],
        tools=None,
        max_tokens=max_tokens,
    )
    return parse_evals(resp.text)


def parse_evals(text: str) -> list[StepEval]:
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []

    evals: list[StepEval] = []
    for item in data if isinstance(data, list) else []:
        try:
            evals.append(
                StepEval(
                    step=int(item["step"]),
                    reward=_clamp(float(item["reward"])),
                    label=str(item.get("label", "")),
                    why=str(item.get("why", "")),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return evals


def discounted_returns(
    rewards: list[float],
    task_reward: float,
    *,
    gamma: float = 0.9,
    horizon: int = 6,
) -> list[float]:
    """G_t = sum of the next `horizon` step rewards (discounted) plus the discounted
    task reward. Local credit assignment, so a long trajectory doesn't drown a step."""
    n = len(rewards)
    returns: list[float] = []
    for i in range(n):
        g = sum(gamma ** (j - i) * rewards[j] for j in range(i, min(i + horizon, n - 1) + 1))
        g += gamma ** ((n - 1) - i) * task_reward
        returns.append(g)
    return returns


def _clamp(value: float) -> float:
    return max(-1.0, min(1.0, value))
