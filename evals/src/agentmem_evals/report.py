"""Turn results into REPORT.md (+ results.json, + a plot if matplotlib is around)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .metrics import ConditionSummary, Report

_OFFLINE_NOTE = (
    "> **Offline run.** The action agent is scripted, so these numbers show the "
    "pipeline working and the memory-vs-baseline contrast, not the finer ordering "
    "between memory conditions (which needs a real model). Run `--live` with a key "
    "and a `--max-usd` cap for that."
)


def write_report(report: Report, out_dir: Path, *, meta: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)

    (out_dir / "results.json").write_text(
        json.dumps(
            {
                "meta": meta,
                "results": [r.to_dict() for r in report.results],
                "summaries": [s.to_dict() for s in report.summaries],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    plot_name = _try_plot(report.summaries, out_dir)
    (out_dir / "REPORT.md").write_text(_markdown(report, meta, plot_name), encoding="utf-8")
    return out_dir / "REPORT.md"


def _markdown(report: Report, meta: dict[str, Any], plot_name: str | None) -> str:
    lines = ["# AgentMem eval report", ""]
    mode = meta.get("mode", "offline")
    lines.append(
        f"Mode **{mode}** · {meta.get('tasks', '?')} tasks · {meta.get('seeds', '?')} seed(s)"
        f" · memory model `{meta.get('memory_model', '-')}`"
    )
    lines.append("")
    if mode == "offline":
        lines += [_OFFLINE_NOTE, ""]

    lines.append(
        "| Condition | pass@1 | repeated failures | requirement violations | interventions | memory tokens |"
    )
    lines.append("|---|---|---|---|---|---|")
    for s in report.summaries:
        lines.append(
            f"| `{s.condition}` | {s.pass_rate:.0%} ± {s.pass_rate_std:.0%} "
            f"| {s.repeated_failures:.1f} | {s.requirement_violations:.1f} "
            f"| {s.interventions:.1f} | {s.memory_tokens:.0f} |"
        )
    lines.append("")

    if plot_name:
        lines += [f"![pass@1 by condition]({plot_name})", ""]

    lines.append(_takeaway(report.summaries))
    lines.append("")
    return "\n".join(lines)


def _takeaway(summaries: list[ConditionSummary]) -> str:
    by_name = {s.condition: s for s in summaries}
    base = by_name.get("baseline")
    mem = by_name.get("agentmem")
    if not base or not mem:
        return ""
    delta = mem.pass_rate - base.pass_rate
    return (
        f"**Takeaway:** AgentMem lifts pass@1 from {base.pass_rate:.0%} to "
        f"{mem.pass_rate:.0%} (Δ {delta:+.0%}), with "
        f"{mem.repeated_failures:.1f} vs {base.repeated_failures:.1f} repeated failures and "
        f"{mem.requirement_violations:.1f} vs {base.requirement_violations:.1f} requirement violations."
    )


def _try_plot(summaries: list[ConditionSummary], out_dir: Path) -> str | None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None

    names = [s.condition for s in summaries]
    rates = [s.pass_rate for s in summaries]
    errs = [s.pass_rate_std for s in summaries]

    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(names, rates, yerr=errs, capsize=4, color="#4c78a8")
    ax.set_ylabel("pass@1")
    ax.set_ylim(0, 1)
    ax.set_title("pass@1 by condition")
    fig.tight_layout()
    fig.savefig(out_dir / "pass_rate.png", dpi=120)
    plt.close(fig)
    return "pass_rate.png"
