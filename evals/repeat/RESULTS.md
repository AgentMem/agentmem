# What a forgotten fix costs the second time

The confabulation runs show an agent inventing a past it cannot see. The obvious
reply is: so what, does the invention cost anything? This is the first number that
answers that, and it is one seed.

Nothing is planted. click 8.1.7 has real bit-rot: pytest 9.1.1 against its pinned
7.4.0 kills collection through a deprecated `parametrize` at `tests/test_basic.py:239`.
Session 1 walks into it and fixes it, uncommitted. Two chores pass. Session 4 says
`git checkout -- .` and run the suite, which is an ordinary git move that throws the
fix away and puts the wall back, with the context that learned it gone.

Qwen3.6-27B, self-hosted, both arms identical except the memory layer.

| session 4 | no memory | memory |
|---|---|---|
| times it hit the wall | **2** | **1** |
| turns from the wall back to green | **20** | **13** |
| how the session ended | **ran out of turns** | finished |

## What the memory arm was told

Two of the three reminders in the whole run fired in session 4, and they are on the
nose:

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

One seed. A single run cannot separate a 20-turn recovery from a 13-turn one; the
number to trust here is the mechanism, not the margin.

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
