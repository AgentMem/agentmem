# Receipts

Every headline number, the committed artifact it is computed from, and the
check that recomputes it. Regenerate this table and verify every row with:

    python3 evals/check_receipts.py --write

A row can be OK (recomputed and equal), FAIL (the writeup and the artifact
disagree, which blocks), or LOST (the artifact no longer exists and the
writeup says so in plain sight rather than hoping nobody asks).

| status | claim | writeup | artifact |
|---|---|---|---|
| OK | click run 1: 0/4 vs 5/0 | evals/realworld/RESULTS.md | `evals/report/realworld-probe.json` |
| OK | click run 2: 0/3 vs 4/1 | evals/realworld/RESULTS.md | `evals/report/realworld-probe-click-r2.json` |
| OK | attrs: 0/3 vs 2/0 | evals/realworld/RESULTS.md | `evals/report/realworld-probe-attrs.json` |
| OK | more-itertools: 0/4 vs 5/0 | evals/realworld/RESULTS.md | `evals/report/realworld-probe-more-itertools.json` |
| OK | ledger, click r2 | evals/realworld/RESULTS.md | `evals/report/account-click-r2.json` |
| OK | ledger, attrs | evals/realworld/RESULTS.md | `evals/report/account-attrs.json` |
| OK | ledger, more-itertools | evals/realworld/RESULTS.md | `evals/report/account-more-itertools.json` |
| OK | seed 1: 20 vs 13 | evals/repeat/RESULTS.md | `evals/report/repeat-click-s1.json` |
| OK | seed 2: 14 vs 12 | evals/repeat/RESULTS.md | `evals/report/repeat-click-s2.json` |
| OK | seed 3: 17 vs 8 | evals/repeat/RESULTS.md | `evals/report/repeat-click-s3.json` |
| OK | attrs 1: the accidental control, 22 vs 12 on zero reminders | evals/repeat/RESULTS.md | `evals/report/repeat-attrs-s1.json` |
| OK | attrs 2: 16 vs 13 | evals/repeat/RESULTS.md | `evals/report/repeat-attrs-s2.json` |
| OK | repeat reminders: 12/12 at temperature 0 | evals/audit/RESULTS.md | `evals/report/audit-repeat.json` |
| OK | airline 50: 37 vs 38, net +1 | evals/tau2/RESULTS.md | `evals/report/tau2-airline-full.json` |

What this does and does not prove: it proves the prose matches the raw run
records, so inventing a number requires inventing an artifact, not a sentence.
It cannot prove the artifacts themselves were not fabricated; nothing can.
What makes fabrication a bad bet here is that every run is reproducible from
a pinned command in its writeup, on open weights, mostly at zero API cost,
so any reader can spend a few dollars and catch us. Cheap to check beats
trust me.
