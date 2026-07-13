# longdebug_causal/

Five multi-session debugging tasks where the root cause is far from the symptom, in
both time (it surfaces sessions later) and meaning (semantic search points at the
wrong file). They exist to measure one thing: does a causal edge beat a plain bank?

Each task exercises a different edge relation (`caused_by`, `fixed_by`, `rules_out`,
`blocks`, `supersedes`) and compares a plain memory bank against one carrying causal
edges. The per-task setup lives in each `CT-*/` directory; grading truth is in `gold/`.

## Status

The causal **mechanism** these tasks measure is built and tested:

- `MemoryEdge` + the `memory_link` tool + validation and cascade delete (`test_causal.py`)
- causal-chain reminders (the cause/fix rides along on the bullet), the counterfactual
  intervention condition, and the causal-aware prompts
- `agentmem bank --graph`, edges in the SessionStart digest
- an end-to-end test proving the chain reaches the reminder through a real session

What's **not** here yet: the tasks as runnable Docker environments, and the live
numbers. Each task needs a real action agent (a model that actually gets pulled toward
the distractor) plus an LLM judge for root-cause scoring — a scripted offline agent
can't reproduce that pull. `smoke.py` validates every task's trap deterministically
offline; running the with-causal vs without-causal comparison across seeds is the
remaining work, gated on a key and a budget.
