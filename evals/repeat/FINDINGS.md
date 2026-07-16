# What the repeat eval taught us, beyond a turn count

The turn numbers are still small and noisy. The diagnostics behind them are not, and
they point the algorithm work more clearly than any single measurement.

## The harness was measuring the product with its main feature off

The first version opened a fresh `MemorySession` per ticket. Each ticket got its own
bank, and the project tier needs three ticket boundaries on one bank before anything
promotes, which a four-ticket run of one-boundary banks never reaches. So every
reminder those seeds fired cited an entry the same session had just written:
cross-session recall, the thing this layer exists for, was never in the test.

Fixed to one session with a boundary per ticket, the shape the daemon ships. The
attrs seed that had stayed silent 26 times now fires 5 reminders and beats its
baseline. That silence was never restraint; it was a bank the reminder could not see.

## But one seed got slower, and it is the useful one

attrs seed 2 with recall on: memory 18 turns, baseline 15. The layer had the real
diagnosis in the bank the whole time. The one reminder it chose to fire said:

> `(P-007)` The next step is to find the largest test file in /work/tests/.

That is a status note from ticket 3's counting chore. It has nothing to do with the
wall in ticket 4. The relevant entry, a written-out diagnosis of the `assoc`
deprecation from an earlier ticket, was in the bank and was not surfaced. The agent
then grepped the wrong path (`src/attrs/funcs.py`, the real file is
`src/attr/_funcs.py`) and lost six turns, while a reminder pointed it at a chore.

The layer remembered the right thing and injected the wrong one. Right time, wrong
content. That is not a recall failure and not a plumbing failure; it is a targeting
failure, and it is the same shape as the tau2 null, where the layer engaged 35 times
across 50 tickets and moved the pass rate by one.

## What this makes the next work

1. **A recall metric for the quality of silence.** Precision is already measured
   (the audit's faithful/harmful). Recall is not: how often, when the agent hits a
   wall the bank already knows, does a relevant reminder fire within k turns. It is
   computable from telemetry and the command log we already save, at zero cost, and
   it is the number every trigger and prompt change should be judged on.

2. **A trigger that matches a stored failure signature.** The current triggers are
   cadence, repeated command, and tool failure. None of them is "this output matches
   a failure this bank has seen", which is exactly the attrs wall (two failing tests,
   not a repeated command). Deterministic, no model call, and it targets the case
   these two seeds missed.

3. **Injector selection that prefers a diagnosis to a status note.** attrs 2 shows
   the ranking is wrong: a recent working note outranked an older, more relevant
   diagnosis. This is where the turn count will actually move.

The turn count is not the finding. The finding is that the layer's bottleneck is
targeting, not memory, and now there is a diagnosis pointing straight at it.
