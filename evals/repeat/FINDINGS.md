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

## The recall metric now exists, and it says 2 of 4

`recall.py` measures the quality of silence deterministically: of the walls where the
bank held a matching entry, how often a relevant reminder actually surfaced. Signature
matching is conservative, code-shaped tokens shared between the wall output and a bank
entry, so it can only undercount. On the four recall-on seeds:

| seed | bank knew | relevant reminder fired | recall |
|---|---|---|---|
| click 1 | yes | no, ticket 4 fired none | 0 |
| click 2 | yes | yes | 1 |
| attrs 1 | yes | yes | 1 |
| attrs 2 | yes | no, it fired an unrelated chore note | 0 |

**2 of 4.** Half the time the layer had the answer and did not surface it at the wall.
That is the number the targeting work has to move, and it is not fooled by turns.

It also caught something the turn count was hiding. click seed 1's "2 turns to green"
is the agent running `pytest -W ignore::PytestRemovedIn10Warning`, which suppresses
the wall rather than fixing it; the scorer saw "passed" and stopped counting, while
the agent went on for eleven more turns to fix it properly. The waste metric counts a
suppressed wall as a recovery, which is one more reason the turn count is not the
finding and recall is the better lens.

## Why the fix is not a trigger

The obvious next step read as "a trigger that fires on a known failure signature". It
is not, because triggers see only the event stream, never the bank, so they cannot
match against stored signatures. And the trigger is not where either recall-0 seed
failed: click 1 ran its step and Phase 2 chose silence, attrs 2 fired but chose the
wrong entry. The miss is in which entry Phase 2 surfaces, which is the bank view it is
given and the salience that orders it. That is the seam the next change works on, and
recall is how it will be judged.

## P0.3: relevance boost, built, gated off, waiting on a measured run

The fix for the recall-0 seeds is in the bank view Phase 2 reads. `render_for_agent`
and `render_tiered_for_agent` order by salience and cap to a top-N, so an old
diagnosis of the error on screen can rank below a fresh generic note and fall off the
cap. `agentmem.relevance` re-orders by relevance to the current window before the cap,
matching code-shaped tokens shared between the window and an entry, salience breaking
ties. It only re-orders entries the bank already holds and never invents one; Phase 2
still decides whether to speak.

It is gated behind `config.relevance_boost`, default off, and the tests prove both
halves: with it off the render is byte-identical to before, and with it on the attrs
seed 2 shape is fixed, a salience-0.2 diagnosis of `test_unknown` surviving a cap of 1
that a salience-0.9 chore note would otherwise have taken.

What it does not have yet is a measured recall. Turning it on and re-running the seeds
is a GPU cost, so it stays off until that run happens, at which point recall.py says
whether 2 of 4 improves. Building it off-by-default is the honest shape: the mechanism
is ready and tested, and the live behavior is provably unchanged until a number
justifies the change.

## The boost was measured, and the verdict is: keep it off

Ran the four seeds again with `relevance_boost` on, same tickets and model.

| | baseline | boost |
|---|---|---|
| recall | 2 of 4 | **4 of 4** |
| turns (click 2 / attrs 1 / attrs 2) | 12 / 15 / 18 | 11 / **17** / 16 |

The recall gain is real and not metric-gaming: reading the reminders, attrs seed 2
now fires the actual diagnosis, `(P-002) all 3 test failures including test_unknown
are caused by...`, where before it fired a chore note. The boost surfaces the right
entry, and the LLM still chose to mention it.

But the turn count, the user-facing number, did not follow: two seeds flat, and attrs
seed 1 got worse, 15 to 17. Recall and the boost are conceptually aligned, both reward
mentioning the wall's tokens, so 4 of 4 confirms the boost does its job more than it
confirms the job helps. With a downside signal present and no user-facing gain shown,
the flag stays off. The mechanism is built, tested, and measured; what it lacks is a
reason to turn on, and this run did not provide one.

