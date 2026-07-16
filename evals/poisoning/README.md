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

## Status

Fixture built and verified offline (`fixture/` plus `check_fixture.py`, no key). The
planted belief is `poison.json`. The live runner is gated behind an explicit spend, in
the same shape as the other live evals here.
