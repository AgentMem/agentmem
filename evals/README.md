# evals/

The evidence, and how sure we are of each piece. Every number below is recomputed
from a committed artifact by `python3 evals/check_receipts.py`, which CI runs on
every push, so inventing one would take inventing an artifact rather than a
sentence. The table of claim to artifact is [RECEIPTS.md](./RECEIPTS.md).

## Where things stand

One result is strong. One is a mechanism without a number. Two are nulls. Nothing
here has run on more than one action model, which is the largest hole.

| question | verdict | detail |
|---|---|---|
| does an agent with no memory invent its own past | **yes, 0 of 5 repos grounded**, and git refutes 7 of 7 checkable claims | [realworld](./realworld/RESULTS.md) |
| does memory make its account of itself true | **partly**: 3 of 4 claims hold, 1 refuted, and the refutation stays in the table | [realworld](./realworld/RESULTS.md) |
| does memory save turns after a context reset | **not established**: an accidental control moved 10 turns with no memory at all | [repeat](./repeat/RESULTS.md) |
| are reminders grounded in what they cite | 12 of 12 at temperature 0, with two caveats found by hand | [audit](./audit/RESULTS.md) |
| tau2-bench airline, 50 paired tickets | **null**: 37 vs 38, net +1 | [tau2](./tau2/RESULTS.md) |
| Terminal-Bench 2.0, 23 paired tasks | **null**, and structurally so | [tbench](./tbench/RESULTS.md) |
| what survives Claude Code's compaction | **harness built and verified dry, never run live** | [compaction](./compaction/README.md) |

## The one that holds

Five repositories that are not ours, four of them real and well-known. Four ordinary
chores, then the context is cleared and the agent is asked what it just did. Without
memory it has never once named something that exists. It invents a file-upload
pipeline in an argument parser, a JWT middleware **in TypeScript** inside a
pure-Python library, an auth service in a class-decorator library, a distributed lock
in a thirty-line package of iterator recipes.

The stories differ every time, so nothing is being recited. The genre never does: it
is always a generic web backend, and a database connection pool fails in most of
them, in projects that have no database.

Grading is a grep against the checkout plus `git status` over the tree the agent
left. No model judges anything. Point it at your own repo with
[`amnesia/run_amnesia.py`](./amnesia/run_amnesia.py).

## The one that got taken away

The waste eval said memory recovers from a re-encountered wall in fewer turns: 20 vs
13, 14 vs 12, 17 vs 8. A fifth seed on a second repo then produced a memory arm that
chose silence 26 times out of 26, which makes it the same configuration as its own
baseline. It finished ten turns faster. Ten turns is wider than three of those four
gaps, so they are not separable from noise. What survives is the mechanism, which
never needed the arithmetic.

## What is missing

- **One model.** Every positive number is Qwen3.6-27B in our own loop.
  [`run_sonnet.sh`](./run_sonnet.sh) is written and gated on an explicit spend.
- **The product surface.** The Claude Code plugin is where a user would meet this and
  it has no live evidence yet.
- **Effect sizes.** Directions are consistent, magnitudes are not pinned.
- **The quality of silence.** The layer stayed quiet 26 times on one wall and spoke 3
  to 5 times on another. Correct restraint and a missed case look identical from
  here, and nothing in this repo can tell them apart.

## The offline harness

Separate from the live evals above: a scripted-agent harness that runs the same task
under five conditions, with no key and no cost.

| Condition | What memory does |
|---|---|
| `baseline` | nothing |
| `agentmem` | maintain a bank, intervene selectively (the real thing) |
| `full_bank` | maintain a bank, dump the whole thing every turn |
| `always_inject` | maintain a bank, always surface its latest entry |
| `injection_only` | no bank; a generic nudge after a failure |

```bash
uv run agentmem-evals                        # all conditions, all tasks, offline
uv run agentmem-evals --live --model-mem claude-haiku-4-5 --max-usd 5 --seeds 3
```

It shows the pipeline working and the selectivity contrast: `agentmem` reaches the
same pass rate as `full_bank` and `always_inject` with far fewer interruptions.
Separating the memory conditions on quality needs a real model, which is what
`--live` is for. Tasks live in `longdebug_mini/tasks/` as `task.toml` + `repo/` +
`verify/`; the harness itself is in `src/agentmem_evals/`.
