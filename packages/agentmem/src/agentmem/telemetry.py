"""One JSONL line per memory-step, including the silent ones."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .agent.memory_agent import StepOutcome


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _window_hash(window_text: str) -> str:
    return hashlib.sha256(window_text.encode("utf-8")).hexdigest()[:12]


class Telemetry:
    """Append-only writer. path=None is a valid no-op sink, so callers never have to
    check whether telemetry is on."""

    def __init__(self, path: str | Path | None) -> None:
        self._path = Path(path) if path else None
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(
        self,
        *,
        session_id: str,
        trigger: str,
        bank_version_before: int,
        outcome: StepOutcome,
    ) -> None:
        if self._path is None:
            return

        result = outcome.result
        intervention = result.intervention
        row: dict[str, Any] = {
            "ts": _now_iso(),
            "session_id": session_id,
            "step": result.step,
            "trigger": trigger,
            "window_hash": _window_hash(outcome.window_text),
            "bank_version_before": bank_version_before,
            "bank_version_after": result.bank_version,
            # Compact record of Phase 1 edits, e.g. [{"created": "K-004"}].
            "tool_calls": [
                {a.effect: a.entry_id} if a.entry_id else {a.effect: True} for a in outcome.applied
            ],
            "decision": result.decision,
            "intervention_text": intervention.text if intervention else None,
            "cited_ids": intervention.cited_ids if intervention else [],
            "reason": intervention.reason if intervention else "",
            "tokens_in": result.usage.input_tokens,
            "tokens_out": result.usage.output_tokens,
            "latency_ms": round(result.usage.latency_ms, 1),
            "model": result.usage.model,
        }
        if outcome.state_sig:  # advantage layer on: capture what it saw and did
            row["state_sig"] = outcome.state_sig
            row["advantage"] = outcome.advantage
            row["gate_applied"] = outcome.gate_applied
        with self._path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def close(self) -> None:
        # We open/close per write, so there's nothing to hold.
        pass


def read_events(path: str | Path) -> list[dict[str, Any]]:
    """Load a telemetry file, skipping any corrupt lines."""
    rows: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def format_replay(events: list[dict[str, Any]]) -> str:
    """Render a telemetry file as a per-step timeline for the CLI.

    The point is to make miscalibration easy to spot: which step spoke, what it
    cited, and that the rest stayed silent.
    """
    lines: list[str] = []
    for e in events:
        decision = e.get("decision", "?")
        marker = "🗣" if decision == "inject" else "·"
        header = f"{marker} step {e.get('step'):>3}  [{e.get('trigger', '')}]  v{e.get('bank_version_before')}→v{e.get('bank_version_after')}"
        lines.append(header)
        for call in e.get("tool_calls", []):
            for effect, target in call.items():
                lines.append(
                    f"      edit: {effect} {target if target is not True else ''}".rstrip()
                )
        if decision == "inject":
            for bline in (e.get("intervention_text") or "").splitlines():
                if bline.startswith("-"):
                    lines.append(f"      {bline}")
        cost = f"{e.get('tokens_in', 0)}→{e.get('tokens_out', 0)} tok, {e.get('latency_ms', 0)}ms"
        lines.append(f"      ({cost})")
    return "\n".join(lines)
