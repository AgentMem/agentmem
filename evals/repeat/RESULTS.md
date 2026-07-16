# What a forgotten fix costs the second time

The confabulation runs show an agent inventing a past it cannot see. The obvious
reply is: so what, does the invention cost anything? Three seeds say yes, and say
so consistently enough to be worth reading and small enough to stay careful about.

Nothing is planted. click 8.1.7 has real bit-rot: pytest 9.1.1 against its pinned
7.4.0 kills collection through a deprecated `parametrize` at `tests/test_basic.py:239`.
Session 1 walks into it and fixes it, uncommitted. Two chores pass. Session 4 says
`git checkout -- .` and run the suite, which is an ordinary git move that throws the
fix away and puts the wall back, with the context that learned it gone.

Qwen3.6-27B, self-hosted, both arms identical except the memory layer.

Turns from re-hitting the wall back to a green suite:

| seed | no memory | memory |
|---|---|---|
| 1 | 20, and it ran out of turns before finishing | 13 |
| 2 | 14 | 12 |
| 3 | 17 | 8 |
| **mean** | **17.0** | **11.0** |

Three of three go the same way, and the ranges do not overlap: 14 to 20 without
memory, 8 to 13 with it. That separation is what makes this worth reading, more than
the six-turn mean, because the baseline alone swings by six turns across seeds of the
same ticket. Seed 1 on its own said 20 against 13 and looked like a bigger result than
three seeds support; seed 2 said 14 against 12 and looked like almost none.

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

Three seeds on one repo, one wall, one model. The margin per seed is 7, 2 and 9
turns, so the effect is directionally consistent and its size is not pinned down.
No claim like "35% fewer turns" survives that spread.

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
