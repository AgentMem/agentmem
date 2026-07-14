"""One memory-step, end to end: Phase 1 bank upkeep, then the Phase 2 speak-or-stay-silent call."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ..bank import AppliedCall
from ..config import AgentMemConfig
from ..injector import Injector
from ..llm.base import LLMProvider
from ..policy.layer import AdvantageLayer
from ..policy.state_sig import DecisionContext, state_signature
from ..schemas import Event, MemoryBank, StepResult
from ..util import clip_to_tokens, truncate_middle
from .phase1 import run_phase1
from .phase2 import run_phase2

Redactor = Callable[[str], str]


@dataclass
class StepOutcome:
    """Everything a step produced: the new bank plus detail for persistence and telemetry."""

    bank: MemoryBank
    result: StepResult
    applied: list[AppliedCall] = field(default_factory=list)
    phase2_raw: str = ""
    window_text: str = ""
    # The rest are populated only when the advantage layer is on.
    state_sig: list[str] = field(default_factory=list)
    advantage: dict[str, float] | None = None
    gate_applied: bool = False


class MemoryAgent:
    def __init__(
        self,
        provider: LLMProvider,
        config: AgentMemConfig,
        redactor: Redactor | None = None,
        advantage: AdvantageLayer | None = None,
    ) -> None:
        self._provider = provider
        self._config = config
        self._injector = Injector(config)
        self._redactor = redactor
        self._advantage = advantage

    def run_step(
        self,
        task: str,
        window_events: list[Event],
        bank: MemoryBank,
        step: int,
        *,
        bypass_cooldown: bool = False,
        trigger: str = "",
        steps_since_inject: int = 99,
        project_bank: MemoryBank | None = None,
    ) -> StepOutcome:
        window = self._render_window(window_events)
        task_text = clip_to_tokens(task, self._config.max_task_tokens)

        p1 = run_phase1(
            self._provider, self._config, task_text, window, bank, step, project_bank=project_bank
        )

        # The advantage layer, if on, feeds Phase 2 a prior from similar past states and
        # may gate a would-be reminder back to silence. It never forces a reminder.
        sig: list[str] = []
        prior: str | None = None
        adv = None
        if self._advantage is not None:
            ctx = DecisionContext(
                trigger=trigger,
                window=window_events,
                bank=p1.bank,
                steps_since_inject=steps_since_inject,
                task=task,
            )
            sig = state_signature(ctx)
            adv = self._advantage.retrieve(sig)
            prior = self._advantage.prior_block(adv)

        p2 = run_phase2(
            self._provider,
            self._config,
            task_text,
            window,
            p1.bank,
            prior=prior,
            project_bank=project_bank,
        )

        bullets = p2.bullets
        gate_applied = self._advantage is not None and self._advantage.should_gate(adv)
        if gate_applied:
            bullets = []  # history says injecting here tends to backfire; stay silent

        # The injector bumps injection bookkeeping on the post-Phase-1 bank, so
        # p1.bank is what the session persists after this call.
        intervention = self._injector.build(
            bullets, p1.bank, step, bypass_cooldown=bypass_cooldown, project_bank=project_bank
        )

        result = StepResult(
            step=step,
            bank_version=p1.bank.version,
            decision="inject" if intervention else "silent",
            intervention=intervention,
            usage=p1.usage + p2.usage,
        )
        adv_summary = None
        if adv is not None:
            adv_summary = {
                "v": round(adv.v, 3),
                "q_silent": round(adv.q_silent, 3),
                "q_inject": round(adv.q_inject, 3),
                "n": float(adv.n),
            }
        return StepOutcome(
            bank=p1.bank,
            result=result,
            applied=p1.applied,
            phase2_raw=p2.raw,
            window_text=window,
            state_sig=sig,
            advantage=adv_summary,
            gate_applied=gate_applied,
        )

    def _render_window(self, events: list[Event]) -> str:
        """Last k events, redacted then clipped, one per line."""
        recent = events[-self._config.window_messages :]
        lines: list[str] = []
        for event in recent:
            text = event.render()
            if self._redactor is not None:
                # Redact before truncating so a secret can't hide in a part we'd keep.
                text = self._redactor(text)
            # truncate_middle keeps both ends (the command and its error line).
            lines.append(truncate_middle(text, self._config.max_event_tokens))
        return "\n".join(lines)
