# Recording the compaction demo

A two-minute recording, no narration needed beyond captions. The point on screen:
Claude Code forgets at `/compact`, and the plugin remembers. Everything here is the
manual version of what `run_live.py` automates; nothing is staged beyond picking a
repo where the bit-rot is real.

## Setup, off camera

```bash
git clone https://github.com/pallets/click /tmp/demo-click && cd /tmp/demo-click
git checkout 8.1.7
pip install -e . pytest
agentmem init claude-code        # arm B only; arm A is a bare Claude Code
```

Two terminals, same repo, one with the plugin installed and one without. Use the
same model in both. Do arm A first so nothing about the flow changes between takes.

## On camera, per arm

1. Start `claude`. Ask: `Run the test suite with python -m pytest tests/ -q and fix
   whatever blocks it. Do not commit.`
   It hits the real pytest 9.1.1 vs pinned 7.4.0 collection failure, fixes
   `tests/test_basic.py`, suite goes green. This is upstream bit-rot, not a plant.
2. Ask for one small chore, to grow the context: `Add a short comment above the
   required-option check in src/click/core.py explaining the rule.`
3. Type `/compact`. Wait for it to finish. This is the memory-loss event.
4. Ask: `What did we fix earlier and why was the suite failing? Be specific about
   files and versions.`

## What the takes should show

Arm A typically answers in generalities or invents specifics; on our runs the
no-memory arm produced TypeScript middleware and database pools in this same
repository. Arm B has the digest reinjected by the SessionStart hook and answers
with `tests/test_basic.py`, the parametrize deprecation, and the 9.1.1 against
7.4.0 pin.

Then, still in arm B: `agentmem receipts` in a second pane, so the viewer sees the
reminders that fired, with their citations, rather than taking the answer on faith.

## Honesty notes for the caption

- One take per arm, no retries. If arm A answers well, show that take anyway and
  say so; the four-run numbers in `evals/realworld/RESULTS.md` carry the average,
  the video only has to carry the mechanism.
- The compact is manual; the docs state auto and manual compaction share the
  machinery, and the transcript records the trigger either way.
