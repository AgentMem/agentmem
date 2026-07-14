# Terminal-Bench 2.0: baseline vs AgentMem

The realest test we run: actual Terminal-Bench 2.0 tasks in Docker, driven by the
same minimal terminal agent twice. The baseline arm is the plain loop; the memory
arm attaches a fresh per-trial `MemorySession` whose reminders land in the next
turn. Same tasks, same action model, same caps, so the pass-rate delta is the
memory layer's doing.

This mirrors the setup in arXiv:2607.08716 (their Table 1 reports +8.3pp on the
full 89-task suite with frontier models). We run a budget-capped subset with
cheaper models, so compare deltas, not absolute pass rates.

## One-time setup

harbor needs Python 3.13; keep it out of the workspace venv:

```bash
uv venv ~/harborenv --python 3.13
uv pip install --python ~/harborenv/bin/python harbor
uv pip install --python ~/harborenv/bin/python -e packages/agentmem -e evals
~/harborenv/bin/harbor download "terminal-bench@2.0" -o ~/tb2
```

Docker must be running. Set `ANTHROPIC_API_KEY` in the environment.

## Run

```bash
python evals/tbench/run_live.py \
    --tasks fix-git,overfull-hbox,cobol-modernization \
    --tb-dir ~/tb2/terminal-bench \
    --harbor-bin ~/harborenv/bin/harbor \
    --jobs-dir ~/tb-jobs \
    --run-usd-cap 2.00
```

`--run-usd-cap` is a preflight guard: the script refuses to start if the worst
case (every trial burning its full `--task-usd-cap`) exceeds it. Real spend is
usually far below worst case because most trials stop early.

The agent lives at `agentmem_evals.tbench.harbor_agent:AgentMemTerminalAgent`;
`--ak arm=baseline|memory` picks the arm, `--ak action_model=...` and
`--ak memory_model=...` pick models. Per-trial logs (including the reminder
transcript and the memory bank) land in each trial's `agent/` directory,
verifier verdicts in `results.json`.

## Honesty notes

- Both arms share every knob: truncation, window trimming, turn caps, budget.
  The memory arm pays for its own memory-step calls; the report separates
  `action_usd` from `memory_usd` but the totals include both.
- A trial that hits its budget or turn cap counts as a failure for that arm.
- Banks are per-trial. Nothing carries across tasks, so a delta here measures
  within-episode memory, the paper's setting, not cross-session retention
  (that's `evals/longrun_sim/`).
