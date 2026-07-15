"""MemorySession: the class most users touch."""

from __future__ import annotations

import logging
import queue
import threading
import uuid
from dataclasses import dataclass
from typing import Any

from .agent.consolidation import run_consolidation
from .agent.memory_agent import MemoryAgent, StepOutcome
from .agent.promotion import run_promotion
from .bank import AppliedCall
from .config import AgentMemConfig
from .llm.base import LLMProvider
from .policy.evaluator import StepEval, StepSummary
from .policy.layer import AdvantageLayer
from .policy.policy_store import PolicyStore
from .redactor import make_redactor
from .salience import SalienceWeights, recompute_lifecycle
from .schemas import Event, MemoryBank, StepResult
from .store import SqliteStore, Store, open_store
from .telemetry import Telemetry
from .triggers import Trigger, TriggerState
from .triggers import default as default_trigger

logger = logging.getLogger("agentmem")

# Pushed onto the work queue to tell the worker thread to stop.
_STOP = object()

# How much a graded reminder moves the reinforcement of each entry it cited, clamped
# into [-1, 1]. A reminder that helped nudges its entries up; a useless one nudges down.
_REINFORCE_GOOD = 0.3
_REINFORCE_BAD = -0.2


class MemorySession:
    def __init__(
        self,
        task: str,
        *,
        model: str | None = None,
        store: str | None = None,
        trigger: Trigger | None = None,
        config: AgentMemConfig | None = None,
        provider: LLMProvider | None = None,
        session_id: str | None = None,
        async_worker: bool = True,
    ) -> None:
        self.task = task
        self.session_id = session_id or uuid.uuid4().hex[:12]

        base = config or AgentMemConfig()
        self._config = base.with_overrides(model=model, store=store)
        self._trigger: Trigger = trigger or default_trigger(self._config.trigger_every_n)

        # Provider and store are injectable so tests can pass a fake and skip both
        # the network and the filesystem. Only check config when we're about to build
        # a real provider (an injected one is the caller's business).
        if provider is None:
            _check_provider_ready(self._config, async_worker)
        self._provider = provider or _lazy_provider(self._config)
        self._store: Store = open_store(self._config.store, self._config.state_dir)
        self._telemetry = Telemetry(_telemetry_path(self._config))

        # The learned advantage layer is opt-in; without it the agent is plain M1.
        self._advantage, self._policy_store = _build_advantage(self._config)
        self._agent = MemoryAgent(
            self._provider,
            self._config,
            redactor=make_redactor(self._config.redact_secrets),
            advantage=self._advantage,
        )

        # Cross-session memory: pick up a bank a previous run left behind.
        self._bank: MemoryBank = self._store.load_bank(self.session_id) or MemoryBank()

        # Project-tier memory: durable rules promoted from the session bank at
        # SessionEnd, in their own store so its cap is independent of this session's.
        self._project_store: Store | None = None
        self._project_bank = MemoryBank()
        if self._config.continual_enabled:
            self._project_store = SqliteStore(f"{self._config.state_dir}/project.db")
            self._project_bank = self._project_store.load_bank("project") or MemoryBank()

        # Trajectory + counters, all guarded by _data_lock.
        self._history: list[Event] = []
        self._turn = 0
        self._turn_at_last_step = 0
        self._step = 0
        self._last_inject_step = 0
        self._pending: str | None = None
        self._decisions: list[_Decision] = []  # for the advantage layer to grade at close

        self._data_lock = threading.Lock()
        self._step_lock = threading.Lock()
        self._closed = False

        self._async = async_worker
        self._queue: queue.Queue[Any] = queue.Queue()
        self._worker: threading.Thread | None = None
        if self._async:
            self._worker = threading.Thread(
                target=self._worker_loop, name=f"agentmem-{self.session_id}", daemon=True
            )
            self._worker.start()

    @property
    def bank(self) -> MemoryBank:
        """The current bank. Safe to read and render at any time."""
        with self._data_lock:
            return self._bank

    @property
    def project_bank(self) -> MemoryBank:
        """Durable, cross-session facts promoted from this (and past) sessions.
        Empty when continual memory is off or nothing has been promoted yet."""
        with self._data_lock:
            return self._project_bank

    def pending_context(self) -> str | None:
        """Take the pending reminder, if any. Consumed once (transient); usually None."""
        with self._data_lock:
            reminder, self._pending = self._pending, None
            return reminder

    def observe(self, events: Any) -> None:
        """Record new events; if a trigger fires, run a memory-step.

        Non-blocking in async mode (the step is queued); runs inline in sync mode.
        """
        batch = _coerce_events(events)
        if not batch:
            return

        with self._data_lock:
            self._turn += 1
            self._history.extend(batch)
            state = TriggerState(
                turn=self._turn,
                batch=batch,
                history=list(self._history),
                turns_since_step=self._turn - self._turn_at_last_step,
            )

        reason = self._trigger(state)
        if not reason:
            return

        with self._data_lock:
            self._turn_at_last_step = self._turn
            self._step += 1
            job = _Job(
                step=self._step,
                events=list(self._history),
                reason=reason,
                bypass_cooldown="tool_failure" in reason,
            )

        if self._async:
            self._queue.put(job)
        else:
            self._execute(job)

    def tick(self, reason: str = "manual", *, consolidate: bool = False) -> StepResult:
        """Force a memory-step now and return its result. Bypasses the trigger.

        Used by the CLI demo, tests, and the Claude Code PreCompact hook to save
        state before the transcript is squeezed. `consolidate=True` (what PreCompact
        passes) also runs the merge/fusion pass afterward. PreCompact is the one hook
        allowed a long timeout, so it's the one place besides SessionEnd this runs
        synchronously with the step that triggered it.
        """
        with self._data_lock:
            self._step += 1
            self._turn_at_last_step = self._turn
            job = _Job(
                step=self._step, events=list(self._history), reason=reason, bypass_cooldown=False
            )
        result = self._execute(job)
        if consolidate:
            self._consolidate_if_due()
        return result

    def flush(self, timeout: float | None = None) -> None:
        """Block until every queued memory-step has finished. No-op in sync mode."""
        if self._async:
            self._queue.join()

    def end_session(self, task_reward: float = 0.0) -> None:
        """Mark a logical session boundary: recompute salience/lifecycle, run the
        consolidation ladder, grade the session's decisions, and bump the session
        counter, without tearing the session down.

        Runs on the background worker in async mode, same as a memory-step, so the
        caller's hot path never blocks on an LLM call; in sync mode it runs inline.
        This is what the daemon calls on Claude Code's SessionEnd hook (the daemon
        keeps one session alive per project, across many Claude Code sessions).
        close() calls it too, right before shutting down for good.
        """
        if self._async:
            self._queue.put(_EndSessionJob(task_reward))
        else:
            self._run_end_session(task_reward)

    def close(self, task_reward: float = 0.0) -> None:
        """Stop the worker, persist the bank, release resources. Idempotent.

        `task_reward` (+1 pass / -1 fail) lets the eval runner tell the advantage layer
        how the whole task turned out; a plain session leaves it neutral.

        The guard is what makes the second call free rather than merely harmless.
        Without it, closing twice re-ran end_session against stores that were already
        shut, and promotion failed into a warning that read exactly like the bank
        having lost everything. Two owners closing the same session is ordinary: a
        harness with a per-task teardown hook and a pool that also cleans up after
        itself both have a fair claim to it.
        """
        if self._closed:
            return
        self._closed = True
        self.end_session(task_reward)
        if self._async and self._worker is not None:
            self._queue.put(_STOP)
            self._worker.join(timeout=10.0)
            self._worker = None

        if self._policy_store is not None:
            self._policy_store.close()
        if self._project_store is not None:
            self._project_store.close()

        self._store.close()
        self._telemetry.close()

    def _run_end_session(self, task_reward: float) -> None:
        self._consolidate_if_due()
        with self._step_lock, self._data_lock:
            decisions, self._decisions = list(self._decisions), []
        # Grade before promoting, so this session's reinforcement is already on the
        # entries when promotion decides which have earned their place.
        if self._advantage is not None and self._policy_store is not None:
            self._grade_session(decisions, task_reward)
        with self._step_lock, self._data_lock:
            self._bank.sessions_seen += 1
            self._store.save_bank(self.session_id, self.task, self._bank)
        self._promote_if_due()

    def _consolidate_if_due(self) -> None:
        """Full salience recompute + the merge/fusion pass. A failure anywhere here
        (bad LLM reply, provider error) just leaves the bank as it was. Consolidation
        is maintenance, never load-bearing for correctness."""
        if not self._config.continual_enabled:
            return
        with self._step_lock:
            with self._data_lock:
                bank = self._bank
            try:
                weights = SalienceWeights.from_config(self._config)
                recomputed = recompute_lifecycle(bank, weights)
                update = run_consolidation(self._provider, self._config, recomputed, self._step)
                if update is not None:
                    recomputed = update.bank
                with self._data_lock:
                    self._bank = recomputed
                    self._store.save_bank(self.session_id, self.task, self._bank)
            except Exception as exc:
                logger.warning("consolidation skipped: %s", exc)

    def _promote_if_due(self) -> None:
        """Rewrite whatever's earned its way into the project bank and save both
        sides. Same fail-safe contract as consolidation: any error leaves both banks
        as they were."""
        if self._project_store is None:
            return
        with self._step_lock:
            with self._data_lock:
                session_bank, project_bank = self._bank, self._project_bank
            try:
                new_session, new_project = run_promotion(
                    self._provider,
                    self._config,
                    session_bank,
                    project_bank,
                    self.session_id,
                    self._step,
                )
                with self._data_lock:
                    self._bank, self._project_bank = new_session, new_project
                    self._store.save_bank(self.session_id, self.task, self._bank)
                    self._project_store.save_bank("project", "project memory", self._project_bank)
            except Exception as exc:
                logger.warning("promotion skipped: %s", exc)

    def _grade_session(self, decisions: list[_Decision], task_reward: float) -> None:
        """Grade the session once, then spend the result twice: the policy store gets
        the returns, and (with continual memory on) each cited entry gets reinforced
        by how its reminder was graded. One evaluator call covers both."""
        if self._advantage is None:
            return
        for d in decisions:
            self._advantage.record(
                session_id=self.session_id,
                step=d.step,
                sig=d.sig,
                action=d.action,
                model=self._config.model,
            )
        summaries = [
            StepSummary(step=d.step, edits=d.edits, decision=d.reminder) for d in decisions
        ]
        trajectory = "\n".join(e.render() for e in self._history[-40:])
        # Grading is best-effort; a failed evaluator call just means no new labels.
        evals: list[StepEval] = []
        try:
            evals = self._advantage.finalize(
                self._provider,
                session_id=self.session_id,
                task=self.task,
                trajectory=trajectory,
                summaries=summaries,
                task_reward=task_reward,
            )
        except Exception as exc:
            logger.warning("session grading skipped: %s", exc)
        if evals and self._config.continual_enabled:
            self._reinforce(decisions, evals)

    def _reinforce(self, decisions: list[_Decision], evals: list[StepEval]) -> None:
        """Move each cited entry's reinforcement by the reward its step was graded.
        An entry cited in several steps accumulates across them, clamped to [-1, 1]."""
        reward_by_step = {e.step: e.reward for e in evals}
        with self._data_lock:
            session_touched = project_touched = False
            for d in decisions:
                reward = reward_by_step.get(d.step, 0.0)
                delta = _REINFORCE_GOOD if reward > 0 else _REINFORCE_BAD if reward < 0 else 0.0
                if not delta:
                    continue
                for cid in d.cited_ids:
                    entry = self._bank.entry(cid)
                    in_session = entry is not None
                    if entry is None:
                        entry = self._project_bank.entry(cid)
                    if entry is None:
                        continue
                    lc = entry.lifecycle
                    lc.reinforcement = max(-1.0, min(1.0, lc.reinforcement + delta))
                    session_touched = session_touched or in_session
                    project_touched = project_touched or not in_session
            if session_touched:
                self._store.save_bank(self.session_id, self.task, self._bank)
            if project_touched and self._project_store is not None:
                self._project_store.save_bank("project", "project memory", self._project_bank)

    def __enter__(self) -> MemorySession:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _worker_loop(self) -> None:
        while True:
            job = self._queue.get()
            try:
                if job is _STOP:
                    return
                if isinstance(job, _EndSessionJob):
                    self._run_end_session(job.task_reward)
                else:
                    self._execute(job)
            except Exception:
                # A memory-step must never take down the worker. Log it and keep
                # serving, so a bad key or provider error is diagnosable instead of
                # silently doing nothing.
                logger.exception("memory-step failed; the session continues without it")
            finally:
                self._queue.task_done()

    def _execute(self, job: _Job) -> StepResult:
        # Serialize execution; the LLM calls inside run_step run with only this lock
        # held, never the fast data lock.
        with self._step_lock:
            with self._data_lock:
                bank_before = self._bank
                version_before = bank_before.version

            with self._data_lock:
                since_inject = job.step - self._last_inject_step
                project_bank = self._project_bank

            outcome: StepOutcome = self._agent.run_step(
                self.task,
                job.events,
                bank_before,
                job.step,
                bypass_cooldown=job.bypass_cooldown,
                trigger=job.reason,
                steps_since_inject=since_inject,
                project_bank=project_bank,
            )

            intervention = outcome.result.intervention
            with self._data_lock:
                self._bank = outcome.bank
                if intervention is not None:
                    self._pending = intervention.text
                    self._last_inject_step = job.step
                self._store.save_bank(self.session_id, self.task, outcome.bank)
                # Buffered for the evaluator at session end. It grades both the
                # advantage layer's policy and the reinforcement on each cited entry,
                # so we only keep these when the evaluator will actually run.
                if self._advantage is not None:
                    self._decisions.append(
                        _Decision(
                            step=job.step,
                            sig=outcome.state_sig,
                            action=outcome.result.decision,
                            edits=_summarize_applied(outcome.applied),
                            reminder=intervention.text if intervention else "silent",
                            cited_ids=intervention.cited_ids if intervention else [],
                        )
                    )

            self._telemetry.record(
                session_id=self.session_id,
                trigger=job.reason,
                bank_version_before=version_before,
                outcome=outcome,
            )
            return outcome.result


class _Job:
    """A queued memory-step."""

    __slots__ = ("step", "events", "reason", "bypass_cooldown")

    def __init__(self, step: int, events: list[Event], reason: str, bypass_cooldown: bool) -> None:
        self.step = step
        self.events = events
        self.reason = reason
        self.bypass_cooldown = bypass_cooldown


class _EndSessionJob:
    """Queued by end_session(): consolidate + grade without tearing the session down."""

    __slots__ = ("task_reward",)

    def __init__(self, task_reward: float) -> None:
        self.task_reward = task_reward


@dataclass
class _Decision:
    """One step's decision, buffered until the session ends and gets graded."""

    step: int
    sig: list[str]
    action: str
    edits: str
    reminder: str
    cited_ids: list[str]  # entries this step's reminder cited, for the reinforcement pass


def _build_advantage(config: AgentMemConfig) -> tuple[AdvantageLayer | None, PolicyStore | None]:
    if not config.advantage_enabled:
        return None, None
    store = PolicyStore(f"{config.state_dir}/policy.db")
    return AdvantageLayer(store, config), store


def _summarize_applied(applied: list[AppliedCall]) -> str:
    parts = [f"{a.effect} {a.entry_id}" if a.entry_id else a.effect for a in applied]
    return ", ".join(parts) or "no edits"


def _telemetry_path(config: AgentMemConfig) -> str | None:
    if not config.telemetry:
        return None
    return config.telemetry_path or f"{config.state_dir}/telemetry.jsonl"


def _lazy_provider(config: AgentMemConfig) -> LLMProvider:
    # Deferred so a session built with an injected provider never touches the SDK.
    from .llm import make_provider

    return make_provider(config)


def _check_provider_ready(config: AgentMemConfig, async_worker: bool) -> None:
    """Catch a missing key or an unsupported model at construction. A sync session
    (a script or the demo) raises so the caller sees it immediately; the daemon runs
    async and only warns, so a hook still returns fast instead of 500-ing."""
    from .llm import preflight

    problems = preflight(config)
    if not problems:
        return
    message = "AgentMem can't reach a model: " + "; ".join(problems)
    if async_worker:
        logger.warning(
            "%s. Memory is running but every step will fail until this is fixed.", message
        )
    else:
        raise RuntimeError(message)


def _coerce_events(events: Any) -> list[Event]:
    """Normalize whatever the caller passed into a list of Events.

    Integrations pass Event objects; the forgiving path (dicts, bare strings) keeps
    quick scripts and the REPL pleasant.
    """
    if events is None:
        return []
    if isinstance(events, Event):
        return [events]
    if isinstance(events, (str, dict)):
        return [_coerce_one(events)]
    if isinstance(events, list):
        return [_coerce_one(e) for e in events]
    raise TypeError(f"Cannot interpret {type(events).__name__} as trajectory events")


def _coerce_one(event: Any) -> Event:
    if isinstance(event, Event):
        return event
    if isinstance(event, str):
        return Event(kind="message", role="assistant", text=event)
    if isinstance(event, dict):
        return Event.model_validate(event)
    raise TypeError(f"Cannot interpret {type(event).__name__} as a trajectory event")
