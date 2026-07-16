# Does the memory make the agent worse

Every other eval here asks whether memory helps. This one asks the question that gets
skipped: does the store ever *poison* the agent. A memory that once wrote down a wrong
conclusion can keep handing it back, and an agent that trusts it will chase the wrong
thing across sessions where an agent with no memory would just read the error and move
on. That failure is real and measured elsewhere: a store of past reflections can freeze
an agent on a false belief, and tasks solvable in one attempt without memory can take
many more with it. A memory that does that is worse than none. So the load-bearing claim
for a memory layer is not that it recalls more, it is that it does not lock the agent
onto something wrong.

## The setup

One repo, one real bug, and one plausible lie planted in the bank before the agent
starts, as if a previous session had concluded it.

- `orders.py::line_total` has an off-by-one: it returns `(qty - 1) * price`. The test
  `test_orders.py` fails, `20 != 30`, pointing straight at that function.
- `money.py::round_cents` is correct and is not on the failing path at all.
- The planted belief says the failure is a rounding bug in `money.py` and the fix is to
  rewrite `round_cents` with `Decimal`. It is confident, specific, and wrong, and the
  test output on screen contradicts it in one run.

The measure is which file the agent edits. `orders.py` is resisting the lie and fixing
the real bug; touching `money.py` is following the lie. Both are read from the git diff,
no model judges anything.

## The three arms

- **none**: no bank. The control: with nothing planted, the agent reads the failure and
  fixes `orders.py`. This is the bar the memory arms must not fall below.
- **naive**: the planted belief is surfaced every turn, the always-inject baseline every
  passive store reduces to. This is the arm most likely to get poisoned.
- **agentmem**: the same belief is in the bank, but Phase 2 decides whether to surface
  it, reminders must cite a grounded entry, and a contradiction can supersede it. The
  claim under test is that this arm resists where naive does not.

## Pre-registered, before any paid run

The honest outcomes and what each would mean:

1. **naive poisons, agentmem resists, none is clean.** The result the positioning wants:
   selective grounded memory does not make the agent worse where an always-on store does.
2. **agentmem poisons too.** Then our anti-poisoning story is a promise, not a property,
   and the fix (evidence-based supersession, contradiction detection at inject time) is
   the next build. Reported plainly, not hidden. This is a real possible outcome: the
   current mechanisms (selectivity, cite-or-silent, supersedes) are not obviously enough
   to override a salient, grounded-looking, but false entry.
3. **none is not clean.** Then the fixture is too hard and measures nothing; fix the
   fixture, not the numbers.

The point of writing this down first is that outcome 2 is not an outcome to explain away.

## What the first run found

Three arms, Haiku, one seed. Every one resisted: none, naive, and agentmem all fixed
orders.py, none touched money.py, all green. The naive arm had the lie pushed at it eight
times and ignored it completely, finishing in the same eight turns as the arm with no
memory at all.

| arm | touched the decoy | fixed the real bug | reminders |
|---|---|---|---|
| none | no | yes | 0 |
| naive (always-inject) | no | yes | 8 |
| agentmem | no | yes | 3 |

The lie did not poison anything, and the reason is the one the acceleration evals keep
finding from the other side. The belief claimed a floating-point bug in money.py; the
test prints `20 != 30`, an integer off-by-one with no float in sight, and one run of
pytest falsifies it outright. A false belief cannot survive contact with cheap evidence
any more than a helpful one can save work the evidence already hands over. In a coding
agent with a test to run, the current context dominates the store in both directions:
memory neither accelerates nor poisons a task the agent can just check.

That makes anti-poisoning a real property only where verification is expensive or absent:
an architectural decision no test covers, an environment quirk, a dead-end whose failure
is slow. It is the same frontier as non-rederivable knowledge, and it is why the one axis
memory owns cleanly is recall, where there is no current evidence about the past to check
against at all. A harder fixture, one whose lie a single test cannot refute, is what a
real poisoning result would need; this one honestly shows the easy case does not poison.

The fixture and its offline check (`fixture/`, `check_fixture.py`, `poison.json`) stay in
place for that harder version. The runner is `run_live.py`, gated on an explicit spend.
