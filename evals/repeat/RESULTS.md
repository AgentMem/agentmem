# What a forgotten fix costs the second time

The confabulation runs show an agent inventing a past it cannot see. The obvious
reply is: so what, does the invention cost anything? This is the first attempt at
an answer, and it is two seeds that disagree about the size of it.

Nothing is planted. click 8.1.7 has real bit-rot: pytest 9.1.1 against its pinned
7.4.0 kills collection through a deprecated `parametrize` at `tests/test_basic.py:239`.
Session 1 walks into it and fixes it, uncommitted. Two chores pass. Session 4 says
`git checkout -- .` and run the suite, which is an ordinary git move that throws the
fix away and puts the wall back, with the context that learned it gone.

Qwen3.6-27B, self-hosted, both arms identical except the memory layer.

Turns from re-hitting the wall back to a green suite, per seed:

| seed | no memory | memory |
|---|---|---|
| 1 | 20, and it ran out of turns before finishing | 13 |
| 2 | 14 | 12 |

The first seed alone said 20 against 13 and looked like a result. The second says 14
against 12. The baseline moves by six turns between two runs of the same ticket, which
is most of the gap the first seed appeared to show, and it is why one seed was never
going to settle this. On seed 1 the memory arm hit the wall once to the baseline's
twice; on seed 2 both hit it twice.

## What the memory arm was told

This is the part both seeds agree on. Two of seed 1's three reminders fired in
session 4, and they are on the nose:

> `(P-003)` Line 239 in `tests/test_basic.py` uses `itertools.chain` directly in
> `@pytest.mark.parametrize`, triggering the collection error. *[fixed_by P-002]*

> `(P-006)` The file was just reverted to the broken state; the `list(chain(...))`
> fix is lost and needs to be re-applied. *[supersedes P-005]*

The second one describes exactly what the ticket had just done to it.

It shows in the commands. Both arms ran `git checkout -- .`, then hit the wall. From
there the arm with no memory grepped for `parametrize` and read four different
regions of the file looking for the problem. The arm with memory grepped
`chain\|parametrize` on its next turn and went straight to line 239.

## What this is not

Two seeds, and they disagree about the size of the effect. The direction is the same
in both and the margin is not: 7 turns on one, 2 on the other. Nothing here supports
a number like "35% fewer turns", and the honest reading is that the mechanism is
visible and the effect size is not yet measured.

It is also not a pass-rate result. Both arms eventually reached green. What differs
is what it cost, which is the thing compaction and context resets actually tax, and
the thing a pass rate cannot see.

## Reproduce

```bash
python evals/repeat/run_repeat.py \
    --tickets evals/repeat/tickets/click-bitrot.json \
    --action-model litellm/hosted_vllm/Qwen/Qwen3.6-27B \
    --api-base http://localhost:8011/v1 --keep-dir /tmp/repeat
```

Both metrics are counted rather than modelled. The compaction eval decides whether a
rerun was pointless from the tool that ran in between, which needs a notion of which
tools mutate; this loop only has bash, so that would be a guess about what a shell
command did. Hitting the wall is visible in the output and turns are turns.

If neither arm hits the wall, the runner says so and the run measured nothing. That
is the failure mode to watch: the ticket, not the metric, is what brings the wall
back.
