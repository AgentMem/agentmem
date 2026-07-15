# Auditing what the memory layer actually said

A proactive memory layer interrupts an agent that did not ask to be interrupted.
The fear that earns is obvious: what happens when it interrupts with something
wrong? Every bullet AgentMem injects cites a bank entry id, which is the design's
answer to that. This is the first time anyone checked whether the answer holds.

The material is 31 real interventions from nine multi-session causal runs, plus
five more from a run recorded after the fix below.

## What held

**Citation validity at inject time: 31 of 31.** Every reminder cited at least one
id, every id resolved to a real entry, and none was invented. That is the
injector doing its job by construction: `_record_injection` only records ids it
can find, so a hallucinated id from Phase 2 gets dropped rather than shown.

## What did not

**Citations were not durable: 11 of 31 still resolved.** Consolidation merges
near-duplicates and capacity eviction drops cold entries, both of which retire
ids. The archive tier stayed empty in every run. So two thirds of the reminders
an agent had already acted on now pointed at nothing: the id was there, the
entry it named was gone, and the question the citation exists to answer, *why did
it say that*, had no answer left.

The whole point of citing an id is that someone can follow it later. A pointer
that dangles two thirds of the time is a promise, not a feature.

## The fix, and its proof

An `Intervention` now carries `cited_snapshot`: what each cited entry said at the
moment it was shown. Telemetry keeps it. The id remains the pointer; the snapshot
is the evidence, and nothing the bank does afterwards can take it away.

Re-run on the same three tasks with the fix in place:

| | before | after |
|---|---|---|
| reminders carrying their own evidence | 0 of 31 | **5 of 5** |
| reminders auditable after the fact | 11 of 31 | **5 of 5** |

## What this does not tell you

The faithfulness verdicts are not a headline. On the old runs, 9 of the 11
auditable reminders were judged faithful to their entries and 2 misleading, but
those 11 are the ones whose entries happened to survive, which is a
survivor-biased sample and not a rate. The post-fix run is 5 of 5 faithful on 5
interventions, which is too few to mean much on its own.

What changed is not the number. It is that the number can now be computed at all,
over every reminder rather than the third that outlived its evidence.

## Reproduce

```bash
python evals/audit/audit_reminders.py \
    --states '<state-dir>/*/mem/telemetry.jsonl' \
    --model litellm/hosted_vllm/Qwen/Qwen3.6-27B \
    --api-base http://localhost:8011/v1
```

Citation integrity is deterministic and needs no model. Drop `--model` for that
alone. Reminders whose entries cannot be resolved are reported as unresolvable
rather than judged, because a judge handed no entry text will blame the reminder
for the loader's gap; that mistake produced a false 11-of-31 harm rate here
before it was caught.
