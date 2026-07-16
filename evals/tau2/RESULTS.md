# tau2-bench, airline, the paper's other benchmark

Qwen3.6-27B on both sides, self-hosted, nothing billed per token. The whole airline
split, the same fifty tickets for both arms, one ticket at a time for the memory arm
because it shares one bank.

| | no memory | memory |
|---|---|---|
| passed | 37 of 50 | 38 of 50 |
| pass rate | 0.74 | 0.76 |
| tickets lost to errors | 0 | 0 |
| ticket boundaries the bank saw | | 50 |
| fail to pass with memory | | 5 |
| pass to fail with memory | | 4 |
| **net** | | **+1** |

The paper reports +6.8pp here. This run is +2pp, which on fifty paired tickets is
one ticket. Five went one way and four went the other, and a coin does that.

## Why the null is worth reading anyway

Not because it is a number, but because of what it cost to make it an honest one.
Four runs died first, in ways that would each have produced a table:

| attempt | outcome |
|---|---|
| 1 | every call an unknown provider: tau2 hands the model string to litellm as-is, and `litellm/` is this repo's own prefix |
| 2 | every turn empty: `--no-thinking` reached our memory provider but not tau2's agent, so the token budget went to a reasoning trace |
| 3 | a 400 per reminder: Qwen3.6's chat template rejects a system message anywhere but the front, so only the arm carrying reminders broke |
| 4 | the ssh tunnel died and took sixteen of sixteen tickets with it |

Attempt 3 is the one to keep. The memory arm was the only arm that could break,
because it was the only one injecting, and it broke as a 400 buried in a log. Before
that was found the arm reported **3 of 3, a perfect pass rate**, against a baseline
of 6 of 8. It looked like the best result this project had ever produced. It was
thirteen of sixteen tickets already dropped, and the survivors flattering us.

The tunnel was the last of it. tau2 needs no Docker and the box already had Python
3.12, so the harness moved onto the box and talks to vLLM over localhost. Zero
tickets lost in this run, on both arms, which is the one thing the earlier attempts
could never claim.

## What this does and does not say

It does not replicate +6.8pp on this model, and it does not refute it either: a
different action model, a different memory implementation, and fifty tickets against
their number are three reasons a gap this size would not show.

What tempers any reading: the domain policy is in every ticket's system prompt
already. Memory can only earn its place on what the policy does not say, which is a
narrower job than the setup suggests. And the baseline passes 37 of 50 on its own,
leaving thirteen failures to work with.

An earlier draft of this section predicted a null by analogy to Terminal-Bench, and
that reasoning was wrong even though the outcome matched. TB tasks are unrelated to
each other, so memory has nothing to carry and the null there is structural. A tau2
domain is fifty tickets against one policy, one schema and one tool set, which is
the setting this layer is built for. It had its chance here and did not take it.

## Reproduce

```bash
# on the box, not through a tunnel
/workspace/tau2-bench/.venv-tau2/bin/python evals/tau2/run_live.py \
    --domain airline --seed-tag full \
    --action-model litellm/hosted_vllm/Qwen/Qwen3.6-27B \
    --api-base http://localhost:8011/v1 --no-thinking \
    --out tau2-airline-full.json
```

`evals/report/tau2-airline-full.json` is the artifact every number above is computed
from, and `python3 evals/check_receipts.py` recomputes them.
