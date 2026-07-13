# LongRun-sim

A stress test for continual memory. One agent works three small repos over 30
sessions, interleaved (A, B, C, A, B, C, …) so it never gets the same repo twice in a
row. The question is whether AgentMem helps an agent that keeps coming back to the same
projects — without quietly forgetting the long tail, and without dragging one repo's
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

- `metrics.py` — pure scoring over the runner's `SessionRecord`s and `ProbeResult`s.
- `scenario.py` — the 30-session schedule and the retention-probe loader.
- `probes/repo_{a,b,c}.yaml` — hidden questions about each repo's requirements, asked
  from memory after the agent has moved on to the other repos.

## Offline check (no key)

Both scripts self-check their math and their schedule with zero model tokens:

```
python metrics.py --selftest        # scoring math
python scenario.py --selftest       # 30 sessions, interleaved, 3 probes/repo
python scenario.py --print          # see the schedule
```

## Live run

The full run needs an action agent and a real model, so it's gated behind a key and a
budget. It drives 30 sessions through `MemorySession` (continual memory on, advantage
layer on so the reinforcement signal is live), fires the retention probes at the end,
and feeds the records to `metrics.py`. Retention and interference are the numbers that
prove forgetting works the way it should.
