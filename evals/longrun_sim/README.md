# LongRun-sim

A stress test for continual memory. One agent works three small repos over 30
sessions, interleaved (A, B, C, A, B, C, ...) so it never gets the same repo twice in a
row. The question is whether AgentMem helps an agent that keeps coming back to the same
projects, without quietly forgetting the long tail, and without dragging one repo's
lessons into another.

## What it measures

| Metric | What it catches | Bar |
|---|---|---|
| Retention rate | Lessons that decayed away before they should have | ≥ 90% at session 30 |
| Interference rate | Reminders citing a different repo than the one being worked | < 5% |
| Learning-curve slope | Whether the agent actually gets better over time | > 0 |
| Repeated-failure slope | Whether it stops re-making the same mistakes | < 0 |
| Bank-growth ratio | Whether the bank grows without bound (nothing forgotten) | < 1.5 |

The bars live in `metrics.py` (`RETENTION_MIN`, `INTERFERENCE_MAX`, `BANK_GROWTH_MAX`).

## Layout

- `metrics.py`, pure scoring over the runner's `SessionRecord`s and `ProbeResult`s.
- `scenario.py`, the 30-session schedule and the retention-probe loader.
- `probes/repo_{a,b,c}.yaml`, hidden questions about each repo's requirements, asked
  from memory after the agent has moved on to the other repos.

## Offline check (no key)

Both scripts self-check their math and their schedule with zero model tokens:

```
python metrics.py --selftest        # scoring math
python scenario.py --selftest       # 30 sessions, interleaved, 3 probes/repo
python scenario.py --print          # see the schedule
```

## Live run

`run_live.py` drives 30 interleaved sessions through real `MemorySession` lifecycles
(continual memory on, advantage layer on), then reads the accumulated telemetry and the
final bank to print a capabilities dashboard: the four things that set AgentMem apart plus
the long-horizon numbers. It needs no task-solve loop, so it runs on Haiku with a hard
cost cap.

```
python evals/longrun_sim/run_live.py --dry-run           # offline plumbing check, no key
ANTHROPIC_API_KEY=... python evals/longrun_sim/run_live.py --max-usd 1.0
```

It reports, with numbers from the run:

1. **Structured procedural memory** - entries by kind and tag (a typed store, not a blob).
2. **Causal memory** - the `caused_by` / `fixed_by` / `rules_out` edges built across sessions.
3. **Proactive intervention** - injects on recurring-failure sessions vs silence on routine.
4. **Learned policy** - advantage estimates recorded and graded over the 30 sessions.

Plus retention (against a no-memory baseline), interference, and bank growth. Interference
is measured on one shared bank across all three repos (the hard case); in production
AgentMem scopes memory per project, so cross-repo citation is structurally near zero.

## Latest numbers (July 2026, `claude-haiku-4-5`, ~$0.30/run)

| Metric | No memory | With AgentMem | Bar |
|---|---|---|---|
| Retention at session 30 | 0% | **78%** | 90% |
| Probe facts still surfaced by the bank | n/a | **9 of 9** | - |
| Recurring failures caught | none | **3 of 3** | - |
| Bank growth | n/a | **1.08x** | < 1.5 |

The gap between "9 of 9 facts surfaced" and "78% graded" was two one-sentence answers that
quoted a requirement verbatim and tripped the forbidden-term grader; the probe specs were
fixed after that run, so the numbers above are the conservative pre-fix grades.

Run-to-run history worth knowing: the first runs scored 56%. The per-probe breakdown showed
root-cause lessons decaying to dormant while newer entries linked to them, which drove three
lifecycle fixes in the core (revive-on-link, a salience floor for causal-edge endpoints,
salience-ordered digests). Same model and scenario afterward: 78%. That is what this harness
is for.
