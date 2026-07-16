# What a forgotten fix costs the second time

The confabulation runs show an agent inventing a past it cannot see. The obvious
reply is: so what, does the invention cost anything? This page was going to answer
that. A fifth run answered a different question instead, and the honest version is
smaller than the four seeds before it looked.

Nothing is planted. click 8.1.7 and attrs 23.2.0 both have real bit-rot against
modern pytest: click's kills collection through a deprecated `parametrize` at
`tests/test_basic.py:239`, attrs' leaves two tests failing. Session 1 walks into it
and fixes it, uncommitted. Two chores pass. Session 4 says `git checkout -- .` and
run the suite, an ordinary git move that throws the fix away and puts the wall back
with the context that learned it gone.

Qwen3.6-27B, self-hosted, both arms identical except the memory layer. Turns from
re-hitting the wall back to a green suite:

| seed | no memory | memory | reminders that fired |
|---|---|---|---|
| click 1 | 20, and it ran out of turns | 13 | 3 |
| click 2 | 14 | 12 | 4 |
| click 3 | 17 | 8 | 5 |
| attrs 2 | 16 | 13 | 2 |
| **attrs 1** | **22** | **12** | **0** |

## Read the last row first

On attrs seed 1 the memory layer took 26 steps, maintained the bank across 60 edits,
and chose silence every one of them. Nothing was injected. With no reminder,
`pending_context()` returns None and nothing is appended, so that agent saw byte for
byte what the baseline agent saw: same model, same tickets, same context, different
rolls of the dice.

It finished ten turns faster than its own baseline.

That is not a memory result. It is one configuration against itself, and it is the
noise floor of this measurement. Ten turns is wider than three of the four gaps
above. Whatever those gaps are, they are not separable from this.

## What survives

Four seeds where reminders did fire, and the memory arm was faster in four of four.
Four the same way is worth noting and is not worth much: about a one in sixteen coin,
against a noise floor this wide.

The mechanism is what holds, because it does not depend on the turn count. On click,
two of seed 1's three reminders fired in the session where the wall came back:

> `(P-003)` Line 239 in `tests/test_basic.py` uses `itertools.chain` directly in
> `@pytest.mark.parametrize`, triggering the collection error. *[fixed_by P-002]*

> `(P-006)` The file was just reverted to the broken state; the `list(chain(...))`
> fix is lost and needs to be re-applied. *[supersedes P-005]*

The second describes exactly what the ticket had just done to it. It shows in the
commands too: both arms ran `git checkout -- .` and hit the wall, and from there the
arm with no memory grepped for `parametrize` and read four regions of the file
hunting for it, while the arm with memory grepped `chain\|parametrize` on its next
turn and went to line 239. That is a reminder doing a real thing, and it is true
whether or not the arithmetic clears the noise.

## The other thing attrs 1 says

Twenty-six steps, twenty-six silences, where the same layer spoke three to five times
on click. The difference is the wall. click's stops collection, so the agent faces an
error it has seen before, which is what the intervene conditions are written for.
attrs' wall is two ordinary failing tests, and Phase 2 did not judge that worth
interrupting for.

That may be correct restraint. It may be a case the layer should catch and does not.
This run cannot tell those apart, and telling them apart needs a way to measure the
quality of silence, which this project does not have.

## And on a stronger action model, flat

The five seeds above are all Qwen. The click wall was rerun with Claude Sonnet 5
driving instead, three seeds, the bank kept by a cheap model (Haiku 4.5). It is a null,
and a clean one:

| seed | no memory | memory | reminders that fired |
|---|---|---|---|
| click 1 | 4 | 5 | 5 |
| click 2 | 6 | 5 | 5 |
| click 3 | 4 | 4 | 2 |

Fourteen turns each way. Sonnet clears the collection failure in four to six turns with
nothing in front of it, which is most of the room a reminder would have had to save,
and the reminders that fired did not change the count. This is the least favorable
setting the layer has, a strong action model with almost nothing to rediscover, and it
neither helped nor hurt. The confabulation probe on this same model, where memory does
change the outcome, is in `evals/realworld/RESULTS.md`.

## What would settle the turn count

Paired seeds in the dozens, not five, with control arms run on purpose instead of
discovered by accident. At roughly forty minutes a seed that is a day of GPU, and it
is the honest price of the number this page wanted.

## Reproduce

```bash
python evals/repeat/run_repeat.py \
    --tickets evals/repeat/tickets/click-bitrot.json \
    --action-model litellm/hosted_vllm/Qwen/Qwen3.6-27B \
    --api-base http://localhost:8011/v1 --keep-dir /tmp/repeat
```

Swap in `tickets/attrs-bitrot.json` for the second wall. Both metrics are counted
rather than modelled: hitting the wall is visible in the output, and turns are turns.
The two specs need different green regexes because the walls differ in kind; click's
would score a still-failing attrs run as recovered, since `2 failed, 1316 passed`
contains the word passed.

If neither arm hits the wall, the runner says so and the run measured nothing.
