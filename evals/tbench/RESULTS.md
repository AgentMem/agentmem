# Terminal-Bench 2.0 pilot: baseline vs AgentMem

2026-07-14. Six tasks, two arms, Claude Haiku 4.5 for both the action loop and the
memory agent, run on the official harbor harness with Docker sandboxes. Total spend
$1.54 under a $2.00 preflight cap. This is a wiring-validated pilot, not a claim:
at n=6 a one-task swing is 16.7pp, so treat the delta as noise-bounded.

## Result

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

## What the run actually measured

**Memory pays rent here, and that's the finding.** Both arms share one hard USD cap
per task, and the memory arm's cap covers its memory-step calls too. At Haiku
prices with the default trigger cadence, that overhead cost the memory arm 30-50%
of its action turns on the budget-bound tasks (polyglot: 16 turns vs 27; cobol: 14
vs 21). The paper this project implements (arXiv:2607.08716) reports no cost or
token overhead for its memory agent, which runs at every step; this harness prices
the intervention and makes it fight for its budget. Overall the memory arm cost 37%
more for the same outcomes.

**The reminders themselves were grounded and correct.** In polyglot-c-py the
memory agent diagnosed a heredoc truncated before its EOF delimiter, called the
`#define`-based approach fundamentally broken (it was), and by the fourth reminder
had recorded the technique that actually works. The bottleneck was what was left of
the budget after paying for that advice, not the advice.

**Consistent with everything we've measured before:** on short-to-medium tasks a
competent model on a clean path doesn't need a memory layer, and a within-episode
reminder can't repay its cost. The payoff we can demonstrate is long-horizon
(see `evals/longrun_sim/`: 0% vs 78% cross-session retention). Do not tune the
trigger to be chattier because of this table; that trades the quiet-by-design
contract for benchmark points.

## Against the paper's numbers

| | paper (Table 1) | this pilot |
|---|---|---|
| tasks | 85 of Terminal-Bench 2.0 | 6 (easy/medium subset) |
| action model | Claude Sonnet 4.5 | Claude Haiku 4.5 |
| memory model | Claude Opus 4.6 | Claude Haiku 4.5 |
| memory cadence | every step, window k=8 | trigger-based (failure streaks + cadence) |
| budget | not reported | $0.15 hard cap per trial, both arms |
| result | 37.6% -> 45.9% (+8.3pp) | 50% -> 50% (0pp) |

The comparison to run when a bigger budget is approved: the same 85 tasks, a
frontier action model, caps loose enough that no trial dies on budget, 3+ attempts
per task. Rough prices at current rates: Haiku/Haiku about $30, Sonnet-action about
$120-160. Until then the honest sentence is: the harness reproduces their setup
end to end and the mechanism visibly fires; the subset is too small and too
budget-squeezed to test their delta.

## Reproduce

```bash
python evals/tbench/run_live.py \
    --tasks fix-git,cobol-modernization,overfull-hbox,openssl-selfsigned-cert,nginx-request-logging,polyglot-c-py \
    --tb-dir ~/tb2/terminal-bench --harbor-bin ~/harborenv/bin/harbor \
    --jobs-dir ~/tb-jobs --run-usd-cap 2.00
```

Per-trial artifacts (loop transcript, injected reminders, the persisted memory
bank, verifier verdicts) land under the harbor jobs directory; the summary JSON is
written next to them.
