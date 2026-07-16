# What survives Claude Code's compaction

Every Claude Code user hits auto-compact: the transcript is squashed into a summary
and the working details go with it. That is the memory-loss event this plugin exists
for, so this eval measures the plugin on it, in the real product, not in a lab loop.

## The mechanism, verified before any of this was built

From the hooks documentation and this repo's own plugin manifest:

- `PreCompact` fires before compaction (matcher `manual` or `auto`); the plugin runs a
  memory step there and captures the recent window into the bank.
- `SessionStart` fires again with `source: "compact"` after auto or manual compaction,
  and whatever the hook prints is added to the fresh context; the plugin prints the
  bank digest there.
- The transcript marks the event: a `system` entry with `subtype: "compact_boundary"`
  and `compactMetadata.trigger`, then a `user` entry with `isCompactSummary`. The
  scorer keys on these, with field shapes copied from a real transcript.
- `packages/agentmem/tests/test_hookrunner.py::test_a_fact_survives_the_compact_cycle`
  proves the capture-and-recap loop at the product level, offline.

## Design

Same shape as `evals/realworld`: real upstream repo, real bit-rot, no planted trap.

1. Ticket 1 in click 8.1.7: run the suite, fix what blocks it. The agent hits the
   upstream pytest 9.1.1 vs pinned 7.4.0 collection failure and fixes it, uncommitted.
2. Tickets 2 and 3: ordinary chores, which also grow the context.
3. `/compact` at the same point in both arms. Manual and auto compaction are the same
   machinery per the docs; the trigger is recorded in the transcript either way.
4. Ticket 4: discard uncommitted changes and start a clean branch, an ordinary git
   move that brings the same wall back.
5. A probe question about what was fixed and why.

Arms: vanilla Claude Code, and Claude Code with the plugin. The baseline keeps Claude
Code's own compact summary, so the comparison is summary alone versus summary plus
AgentMem, which is the honest one. Both arms run in isolated `CLAUDE_CONFIG_DIR`s.

Metrics, all computed from the transcript by `score.py`:

- tool calls from re-hitting the wall to the suite going green (primary)
- reruns of a command that already failed with no edit in between, which is the
  complaint users actually have; an intervening edit clears the slate, so the count
  can only undercount
- post-compact tokens
- probe groundedness against the checkout, scored by `evals/longdebug_causal/grounding.py`

## Run the free part first

```bash
uv run python evals/compaction/check_harness.py
uv run pytest evals/tests/test_compaction_score.py packages/agentmem/tests/test_hookrunner.py
```

`check_harness.py` drives a schema-faithful mock CLI through the real pty driver and
the real scorer, both arms, and asserts the instrument detects the gap it exists to
measure. No key, no network.

## The paid run

```bash
ANTHROPIC_API_KEY=... uv run python evals/compaction/run_live.py \
    --workroot /tmp/compaction --model haiku --yes-spend
```

Rough cost per arm-seed with haiku is well under a dollar; sonnet for the headline
number is a few dollars per seed. The memory model can point at a self-hosted
endpoint and cost nothing.

The first paid smoke exists to verify what cannot be checked for free, in this order:
that `/compact` typed into the TUI executes rather than opening the command palette,
that `CLAUDE_CONFIG_DIR` isolation plus `ANTHROPIC_API_KEY` auth works headless, that
the transcript lands under the isolated config dir, that project-level hooks fire
from `settings.json` there, and that the idle heuristic survives real streaming.
Any of these failing is a harness bug to fix before an arm comparison means anything.

## Expectations, registered before the first paid run

The memory arm should re-fix the wall in fewer tool calls, with zero no-edit reruns,
and answer the probe grounded. If it does not, that is not a benchmark artifact to
explain away; this is the product's home turf, and a null here is product feedback.
One thing this eval cannot show either way is task pass rates; it measures waste and
recall, which is what compaction actually taxes.
