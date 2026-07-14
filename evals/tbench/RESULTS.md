# Terminal-Bench 2.0: baseline vs AgentMem

2026-07-14. Three budget-capped runs on the official harbor harness with Docker
sandboxes: two with Claude Haiku 4.5 in both roles, then one with Claude Sonnet 5
as the action model to test whether a stronger executor converts memory's advice
into passes. Twenty-three paired tasks for about $14. Headline, stated plainly:
no genuine pass-rate flip in either direction anywhere, and the harness put a
price on the memory layer that the original paper never reports.

## Sonnet-action run (8 tasks, $0.55/trial cap, 40 turns, $7.53)

Claude Sonnet 5 action, Claude Haiku 4.5 memory, on the seven tasks Haiku had
failed plus one anchor it had passed. Two artifact rows from a 30s client timeout
were rerun after the fix (commit deef6ba) and are shown post-rerun.

| task | baseline | memory | baseline cost/turns | memory cost/turns | reminders |
|---|---|---|---|---|---|
| break-filter-js-from-html | fail (budget) | fail (budget) | $0.553 / 17t | $0.561 / 13t | 1 |
| cobol-modernization | fail (budget) | fail (budget) | $0.595 / 18t | $0.602 / 16t | 2 |
| constraints-scheduling | PASS | PASS | $0.161 / 6t | $0.269 / 6t | 0 |
| extract-elf | PASS | PASS | $0.527 / 16t | $0.272 / 10t | 0 |
| overfull-hbox | fail (budget) | fail (budget) | $0.571 / 21t | $0.561 / 18t | 3 |
| polyglot-c-py | fail (task_done, wrong) | fail (no_tool_call) | $0.393 / 9t | $0.151 / 2t | 0 |
| raman-fitting | fail (budget) | fail (budget) | $0.575 / 19t | $0.632 / 17t | 2 |
| vulnerable-secret | PASS | PASS | $0.557 / 20t | $0.512 / 18t | 3 |
| **total** | **3/8** | **3/8** | **$3.93** | **$3.56** | 11 |

Notes that keep this table honest. The polyglot memory row is a harness artifact,
not a memory effect: Sonnet opened with prose twice and the loop's one-nudge rule
ended the trial before any reminder existed; the baseline row failed on its own by
declaring victory the verifier rejected. Sonnet's baseline pass rate here (37.5%)
lands within a point of the paper's Sonnet 4.5 baseline on the full suite (37.6%),
which is luck at n=8, but pleasant luck. And the stronger action model made the
memory layer quieter, 11 reminders across 8 trials versus 43 across 9 in the Haiku
run: fewer failure streaks, fewer triggers, exactly the design intent.

The conversion hypothesis (a stronger executor turns advice into passes) did not
show up at this budget tier either: every hard fail above ran out of its $0.55 cap
mid-investigation in both arms alike.

## Main run (9 tasks, $0.25/trial cap, 40 turns, $4.12)

Medium-difficulty subset chosen to be failure-heavy for a budget action model,
plus the three tasks the pilot below had cut off at a tighter cap.

| task | baseline | memory | baseline cost/turns | memory cost/turns | reminders |
|---|---|---|---|---|---|
| break-filter-js-from-html | fail (budget) | fail (budget) | $0.257 / 36t | $0.254 / 28t | 8 |
| cobol-modernization | fail (budget) | fail (budget) | $0.259 / 32t | $0.254 / 22t | 2 |
| constraints-scheduling | fail (budget) | fail (budget) | $0.255 / 38t | $0.253 / 21t | 3 |
| extract-elf | PASS | PASS | $0.259 / 40t | $0.263 / 24t | 3 |
| kv-store-grpc | PASS | PASS | $0.068 / 14t | $0.121 / 15t | 1 |
| overfull-hbox | fail (max_turns) | fail (budget) | $0.227 / 40t | $0.257 / 26t | 7 |
| polyglot-c-py | fail (max_turns) | fail (budget) | $0.243 / 40t | $0.254 / 24t | 7 |
| raman-fitting | fail (budget) | fail (task_done) | $0.251 / 38t | $0.214 / 22t | 2 |
| vulnerable-secret | fail (task_done) | fail (budget) | $0.179 / 32t | $0.251 / 32t | 10 |
| **total** | **2/9** | **2/9** | **$2.00** | **$2.12** | 43 |

Zero flips in either direction. The rerun answers the pilot's open question: the
three tasks that died on the tight cap still fail with 67% more budget and turns,
so those failures are model capability, not the cap.

The cost split turned into a turn split. With both arms saturating the same cap on
hard tasks, total spend nearly converges (+6% for memory), but the memory arm
consistently got 25-45% fewer action turns for the same money (21 vs 38 on
constraints-scheduling, 22 vs 32 on cobol, 28 vs 36 on break-filter). The memory
calls bought accurate diagnoses and paid for them in exploration turns the action
model still needed.

## Pilot (6 tasks, $0.15/trial cap, 30 turns, $1.54)

| task | baseline | memory | baseline cost/turns | memory cost/turns | reminders |
|---|---|---|---|---|---|
| cobol-modernization | fail (budget) | fail (budget) | $0.165 / 21t | $0.157 / 14t | 1 |
| fix-git | PASS | PASS | $0.023 / 10t | $0.086 / 14t | 4 |
| nginx-request-logging | PASS | PASS | $0.077 / 17t | $0.160 / 18t | 3 |
| openssl-selfsigned-cert | PASS | PASS | $0.074 / 18t | $0.163 / 20t | 1 |
| overfull-hbox | fail (budget) | fail (budget) | $0.156 / 27t | $0.163 / 18t | 1 |
| polyglot-c-py | fail (budget) | fail (budget) | $0.151 / 27t | $0.160 / 16t | 4 |
| **total** | **3/6** | **3/6** | **$0.65** | **$0.89** | 14 |

Same three tasks pass in both arms, same three fail. Pass-rate delta: 0pp.

## What the runs actually measured

**A 15-pair trial-level null, priced.** Across both runs, no paired task ever
flipped in either direction: within-episode memory at Haiku level neither rescued
nor sank a single trial on tasks up to about an hour of expert time. What it did
do, under caps that count memory spend, is trade money and turns for advice: +37%
cost at the tight cap, +6% cost but 25-45% fewer action turns at the loose one.
The paper this project implements (arXiv:2607.08716) runs its memory agent at
every step and reports no cost or token overhead at all; these tables are the
overhead, measured.

**The reminders themselves were grounded and correct.** In polyglot-c-py the
memory agent diagnosed a heredoc truncated before its EOF delimiter, called the
`#define`-based approach fundamentally broken (it was), and by the fourth reminder
had recorded the technique that actually works. The bottleneck was never the
advice; it was what remained of the budget after paying for it, spent by an action
model that needed raw exploration turns more than it needed direction.

**Consistent with everything we've measured before:** on short-to-medium tasks a
competent model on a clean path doesn't need a memory layer, and a within-episode
reminder can't repay its cost at budget-model prices. The paper's own +8.3pp came
from a frontier action model (Sonnet 4.5) with a stronger memory model (Opus 4.6)
and no budget pressure. The payoff we can demonstrate at low cost is long-horizon
(see `evals/longrun_sim/`: 0% vs 78% cross-session retention). Do not tune the
trigger to be chattier because of these tables; that trades the quiet-by-design
contract for benchmark points.

## Against the paper's numbers

| | paper (Table 1) | these runs |
|---|---|---|
| tasks | 85 of Terminal-Bench 2.0 | 23 paired (easy/medium subsets) |
| action model | Claude Sonnet 4.5 | Claude Haiku 4.5, then Claude Sonnet 5 |
| memory model | Claude Opus 4.6 | Claude Haiku 4.5 |
| memory cadence | every step, window k=8 | trigger-based (failure streaks + cadence) |
| budget | not reported | $0.15-0.55 hard cap per trial, both arms |
| result | 37.6% -> 45.9% (+8.3pp) | no genuine flips in 23 pairs (0pp) |

Their delta remains untested by us, not contradicted, and the remaining
differences have narrowed to three: their memory model is Opus-tier, their memory
agent runs at every step, and their trials never die on a budget cap (every hard
fail in our Sonnet run did). The decisive next experiment is caps loose enough
that trials end on their own merits, on the full suite, with 3+ attempts per
task; at current rates that is roughly $250-350 with a Sonnet action model. Until
then the honest sentence is: the harness reproduces their setup end to end, the
mechanism visibly fires and is priced; under hard budget caps the intervention
has not converted to pass-rate at either action-model tier we could afford.

## Reproduce

```bash
# main run
python evals/tbench/run_live.py \
    --tasks cobol-modernization,overfull-hbox,polyglot-c-py,raman-fitting,constraints-scheduling,kv-store-grpc,vulnerable-secret,extract-elf,break-filter-js-from-html \
    --max-turns 40 --task-usd-cap 0.25 --run-usd-cap 4.50 \
    --tb-dir ~/tb2/terminal-bench --harbor-bin ~/harborenv/bin/harbor --jobs-dir ~/tb-jobs

# pilot
python evals/tbench/run_live.py \
    --tasks fix-git,cobol-modernization,overfull-hbox,openssl-selfsigned-cert,nginx-request-logging,polyglot-c-py \
    --tb-dir ~/tb2/terminal-bench --harbor-bin ~/harborenv/bin/harbor \
    --jobs-dir ~/tb-jobs --run-usd-cap 2.00
```

Per-trial artifacts (loop transcript, injected reminders, the persisted memory
bank, verifier verdicts) land under the harbor jobs directory; the summary JSON is
written next to them.
