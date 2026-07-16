# tau2-bench, airline, first live run

Qwen3.6-27B on both sides, self-hosted, nothing billed per token. Sixteen tickets of
the airline split, the same sixteen for both arms.

| | no memory | memory |
|---|---|---|
| passed | 13 of 16 | 13 of 16 |
| tickets lost to errors | 0 | 0 |
| fail to pass with memory | | 1 |
| pass to fail with memory | | 1 |
| **net** | | **+0** |

Nothing moved. That is what was written down before the run, for a reason: the
baseline passes 13 of 16 on its own, so there are three failures available to flip,
and one flip each way on sixteen tickets is noise wearing a number. The result is
here because it happened, not because it says anything. One
caution a reader deserves: the run's JSON died with the stopped instance, so unlike
every other number in this repo these three rows have no committed artifact behind
them, only the log lines this page quotes. `evals/check_receipts.py` lists the entry
as LOST for that reason, and the 50-ticket artifact replaces it when it lands.

## What the run was actually for

Three earlier attempts died in ways that would have made any number a lie, and the
last one is the reason to read this page at all:

| attempt | outcome |
|---|---|
| 1 | every call an unknown provider: tau2 hands the model string to litellm as-is, and `litellm/` is this repo's own prefix |
| 2 | every turn empty: `--no-thinking` reached our memory provider but not tau2's agent, so the token budget went to a reasoning trace |
| 3 | a 400 per reminder: Qwen3.6's chat template rejects a system message anywhere but the front, so only the arm carrying reminders broke |
| 4 | the ssh tunnel died and took sixteen of sixteen tickets with it |

Attempt 3 is worth stating plainly. The memory arm was the only arm that could break,
because it was the only one injecting, and it broke as a 400 buried in a log. Before
that was found, the arm reported **3 of 3, a perfect pass rate**, against a baseline
of 6 of 8. It looked like the best result the project had ever produced. It was
survivorship: thirteen of sixteen tickets had already been dropped.

The tunnel was the last of it. tau2 needs no Docker and the box already had Python
3.12, so the harness moved onto the box and talks to vLLM over localhost. No tunnel,
no failure class: **zero tickets lost**, which is the one thing this run does
establish.

## What would produce a number

The full airline split, both arms, about three hours of one GPU. The infrastructure
is now known clean, which is the only reason that spend is worth anything.

```bash
# on the box, not through a tunnel
/workspace/tau2-bench/.venv-tau2/bin/python evals/tau2/run_live.py \
    --domain airline --seed-tag s1 \
    --action-model litellm/hosted_vllm/Qwen/Qwen3.6-27B \
    --api-base http://localhost:8011/v1 --no-thinking \
    --out /workspace/tau2-airline-s1.json
```

Even then, the paper's claim is +6.8pp, which on fifty paired tickets is about three
net flips. Fifty tickets can show a large effect and cannot resolve a small one, and
that is worth deciding before the spend rather than discovering after it.
