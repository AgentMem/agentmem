# LongDebug-Causal live: memory vs no memory across sessions

Three causal-debugging tasks, each 5-6 sessions in one Docker container whose
workspace survives while the agent's context resets between sessions. At the
start of the final session the agent is asked what originally broke. That probe
is the whole experiment: the work happened, the transcript is gone, and only a
memory layer carries the cause forward.

Run twice on different stacks, and the second run found something the first
could not have.

## Run B: an open model on a rented GPU (2026-07-15, $0 in API)

Qwen3.6-27B does both jobs, action and memory, on one rented card. No API bill,
no budget caps, so trials end on their merits. Two seeds over the three tasks,
six paired runs.

| over 6 pairs | no memory | memory |
|---|---|---|
| **invented a cause that never existed** | **6 of 6** | **0 of 6** |
| root cause: keyword gate | 1 of 6 | 3 of 6 |

**Without memory the model does not forget, it confabulates.** Every single
no-memory answer, across both seeds and all three tasks, blamed a race
condition: an async synchronization layer, a fetch resolving after unmount,
background tasks touching shared state, an async event loop. **None of these
tasks contains a race condition anywhere.** Asked about work it could no longer
see, the model produced a fluent, confident, entirely fictional cause, six times
out of six, in the same shape each time. With the bank attached the same model
did this zero times out of six.

Trust the fabrication row, not the gate row. On seed 3 the no-memory answer for
CT-03 **passed the keyword gate while fabricating a race condition**: it
happened to use enough gold vocabulary while its actual claim was invented. The
gate has now produced false negatives (a correct answer phrased around the
keywords) and a false positive (a fictional answer sprinkled with them), so a
1-of-6 versus 3-of-6 split is not a result worth leaning on. Whether the model
invented its cause is checkable by reading; that is the row that means
something.

This is a different failure from the one Run A found, and a worse one. Sonnet,
with no memory, said plainly that it had no access to earlier sessions: blind
but honest. Qwen invents. A developer can act on "I don't know"; they cannot act
safely on a confident wrong answer.

With the bank attached, the same model stayed on the ground it had actually
covered. It is not always right, but it is always answering about this project:

- **CT-01** traced `display_name` in `schema/user.yaml` to the missing entry in
  `tools/codegen.py`'s list and named regeneration as the fix, on both seeds.
- **CT-05** pinned the httpx conflict to `constraints.txt` specifically, the
  buried second pin the task is built around, **and which the Sonnet run in Run
  A missed**. A cheaper model with a good bank beat a stronger model without
  one, on the hardest task in the set. The second seed reached the version
  incompatibility but not the file, so it scores a fail.
- **CT-03** is memory's weakest task: seed 2 described the real CI JobTimeout
  but missed the gold vocabulary, and seed 3 blamed a broken virtual
  environment, which is wrong. Both count as fails. The bank kept it inside the
  project; it did not make it correct.

Recording note: these multi-session runs produce about 27 graded decisions per
task, roughly six times what a one-shot terminal trial yields, which makes them
the better feedstock for the advantage layer as well as the better experiment.

## Run A: frontier action model, paid (2026-07-14, $5.82 including the judge)

Claude Sonnet 5 works the tickets, Claude Haiku 4.5 runs the memory agent, Haiku
judges the probe. One seed. Small n, read it as a directional signal, not a
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

Run B, on a model you host yourself. Nothing here is billed per token, so the
preflight reports a worst case of zero and never asks for a key:

```bash
python evals/longdebug_causal/run_live.py \
    --tasks CT-01,CT-03,CT-05 --conditions none,memory \
    --action-model litellm/hosted_vllm/Qwen/Qwen3.6-27B \
    --memory-model litellm/hosted_vllm/Qwen/Qwen3.6-27B \
    --api-base http://localhost:8011/v1 --no-judge --seed-tag s2 \
    --session-usd-cap 5.0 --run-usd-cap 0.01
```

Run A, on the paid stack:

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
