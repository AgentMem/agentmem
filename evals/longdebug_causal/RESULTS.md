# LongDebug-Causal live: memory vs no memory across sessions

2026-07-14. Three causal-debugging tasks, each 5-6 sessions in one Docker
container whose workspace survives while the agent's context resets between
sessions. Claude Sonnet 5 works the tickets, Claude Haiku 4.5 runs the memory
agent, Haiku judges the root-cause probe. Two conditions per task, one seed,
about $5.82 including the judge. Small n, read it as a directional signal, not a
p-value. But the direction is unambiguous and it is the opposite of the
Terminal-Bench result, for a reason that matters.

## Result

| task | condition | root cause identified | repeated-cause rate | cost |
|---|---|---|---|---|
| CT-01 stale-artifacts | no memory | no | 0.50 (1 of 2) | $0.94 |
| CT-01 stale-artifacts | memory | **yes** (judge 1.0) | **0.00** (0 of 2) | $0.99 |
| CT-03 ruled-out | no memory | no | 0.50 (1 of 2) | $0.98 |
| CT-03 ruled-out | memory | partial (judge 0.5) | n/a (no opportunity) | $1.07 |
| CT-05 stale-pin | no memory | no | 0.00 (0 of 1) | $0.77 |
| CT-05 stale-pin | memory | no (grounded, mis-graded) | 0.00 (0 of 1) | $1.05 |
| **totals** | no memory | **0 of 3** | | $2.69 |
| | memory | **1 of 3 full, 3 of 3 substantive** | | $3.11 |

## Why the baseline scores zero, and why that is the whole point

The root-cause probe is asked at the start of the final session, after the
context reset. In all three tasks the no-memory agent opened its answer by saying
it has no access to previous sessions and each conversation starts fresh. It is
not wrong about itself. That is behavioral state decay stated in the agent's own
words: the work happened, the transcript is gone, and nothing carries the cause
forward. A within-session-competent frontier model scores zero on cross-session
root cause because there is nothing to reason from.

With AgentMem attached, the same model answered substantively in all three:

- **CT-01** nailed it. The bank had recorded that the generated models and
  fixtures were stale relative to the schema, so the wrap-up correctly named the
  derivation-freshness failure and the `make generate` fix (judge 1.0, keyword
  gate passed), and the trap never recurred (0.00 vs the baseline's 0.50).
- **CT-03** was partial: the judge gave 0.5 for tracing the JobTimeout past the
  misleading "just bump the timeout" ticket, but the answer missed the exact
  gold phrasing, so the keyword gate failed and it does not count as identified.
- **CT-05** is the honest miss and worth keeping visible. The memory answer
  correctly pinned the httpx version and named `constraints.txt`, but framed it
  as a simple removed-kwarg bug plus a later migration, rather than the two-pin
  story the task tests (a second buried pin the upgrade missed, an old diagnosis
  that had to be superseded). Keyword gate passed, judge scored it 0.0. The
  memory surfaced the right neighborhood; the synthesis missed the causal
  supersede. That is a real limitation of a Haiku memory agent on the hardest of
  the five relations, not a plumbing bug.

## Read against Terminal-Bench

These two evals bracket the claim. On Terminal-Bench, within a single episode, a
capable model on a clean path gained nothing from memory and paid for the calls.
Here, across sessions, the baseline is structurally blind and memory is the only
reason the agent can answer at all. AgentMem is not a within-task accelerator; it
is what keeps a long-horizon agent from forgetting why something broke. The
product line follows: turn it on for the project that spans days, not the task
that spans minutes.

## Reproduce

```bash
python evals/longdebug_causal/run_live.py \
    --tasks CT-01,CT-03,CT-05 --conditions none,memory \
    --action-model claude-sonnet-5 --memory-model claude-haiku-4-5 \
    --run-usd-cap 6.60
```

`--fake-action` drives the whole pipeline offline for free (no key, no cost) to
check the Docker and grading wiring before spending. Per-task JSON, including
every session's diff, hidden-verifier snapshot, and the wrap-up answer, lands at
`evals/report/causal-live.json`.
