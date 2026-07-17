# Action-audit detection

Does the action-receipt engine catch what it claims to? This scorecard runs the verifier
over labeled scenarios with a known ground truth and measures detection. No model, no key:
it is pure logic against a real filesystem diff, so the numbers are recomputable by CI.

```bash
uv run python evals/action_audit/run.py
```

Each scenario sets up a small tree, applies the ops an agent would run, feeds the verifier
the agent's claim (and any checks it was gated on), and compares the flagged issues to the
ground truth. Two kinds of cases: ones that should raise an issue (fabrication, overreach,
silent failure), and ones that must *not* trip a false alarm (lockfile churn, a claimed
deletion, a nested-path claim, a failing check with no success claim).

## Latest numbers

Twelve scenarios, from `evals/report/action-audit.json`:

| Metric | Result |
|---|---|
| Scenarios labeled exactly right | 12 / 12 |
| Injected issues caught (recall) | 7 / 7, 100% |
| False alarms on faithful runs (precision) | 0, 100% |

The bar is a perfect card: every injected issue caught, nothing invented. `run.py` exits
non-zero if that slips, so CI holds the line.

## What this is and is not

This measures the *verifier*, not an agent. It shows the receipt engine reliably separates
a truthful account from a fabricated, overreaching, or silently-failing one, on ground
truth we control. It does not claim anything about how often real agents lie; that needs a
live study on real trajectories, which is the honest next step.
