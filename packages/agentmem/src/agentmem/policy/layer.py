"""The advantage layer as one object the agent talks to.

It holds the graded history, turns a state into a prior ("in N similar states,
injecting averaged +0.4, silence −0.1") for the Phase 2 prompt, and offers a one-way
gate that can turn a would-be reminder into silence when history says injecting here
tends to backfire. It never turns silence into a reminder. At SessionEnd it runs the
evaluator and writes the returns back so the next session is a little wiser.
"""

from __future__ import annotations

from ..config import AgentMemConfig
from ..llm.base import LLMProvider
from .advantage import Advantage, estimate
from .evaluator import StepEval, StepSummary, discounted_returns, evaluate
from .policy_store import PolicyStore


class AdvantageLayer:
    def __init__(self, store: PolicyStore, config: AgentMemConfig) -> None:
        self._store = store
        self._gate_on = config.advantage_gate
        self._tau = config.advantage_gate_tau
        self._min_neighbors = config.advantage_min_neighbors
        # Snapshot the graded history once; a session doesn't grade itself until it ends.
        self._records = store.finalized()

    def retrieve(self, sig: list[str]) -> Advantage | None:
        return estimate(sig, self._records)

    def prior_block(self, adv: Advantage | None) -> str | None:
        if adv is None or adv.n < 1:
            return None
        return (
            f"Historical evidence: in {adv.n} similar past states, injecting averaged "
            f"return {adv.q_inject:+.2f} (n={adv.n_inject}) and staying silent "
            f"{adv.q_silent:+.2f} (n={adv.n_silent}). Weigh this; it is a hint, not a rule."
        )

    def should_gate(self, adv: Advantage | None) -> bool:
        """True to force silence: enough evidence, and injecting looks worse than silence."""
        if not self._gate_on or adv is None:
            return False
        return adv.n >= self._min_neighbors and adv.a_inject < self._tau

    def record(
        self, *, session_id: str, step: int, sig: list[str], action: str, model: str
    ) -> None:
        self._store.record(
            session_id=session_id,
            step=step,
            state_sig=sig,
            action=action,
            inject_class=None,
            model=model,
        )

    def finalize(
        self,
        provider: LLMProvider,
        *,
        session_id: str,
        task: str,
        trajectory: str,
        summaries: list[StepSummary],
        task_reward: float,
    ) -> list[StepEval]:
        """Grade the session and write discounted returns back to the policy store.

        Returns the raw per-step evals too, so the reinforcement pass can credit or
        debit the entries each reminder cited without paying for a second grading call.
        """
        evals = evaluate(
            provider,
            task=task,
            trajectory=trajectory,
            task_result=_result_label(task_reward),
            steps=summaries,
        )
        if not evals:
            return evals
        by_step = {e.step: e.reward for e in evals}
        steps = sorted(by_step)
        returns = discounted_returns([by_step[s] for s in steps], task_reward)
        self._store.finalize(session_id, dict(zip(steps, returns, strict=True)))
        return evals


def _result_label(task_reward: float) -> str:
    if task_reward > 0:
        return "pass"
    if task_reward < 0:
        return "fail"
    return "unknown"
