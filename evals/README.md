# evals/

The evidence. Storage-style memory is easy to hand-wave about; this harness
*measures* whether proactive, selective intervention actually helps, by running the
same action agent under five conditions and comparing.

## Conditions

| Condition | What memory does |
|---|---|
| `baseline` | nothing |
| `agentmem` | maintain a bank, intervene selectively (the real thing) |
| `full_bank` | maintain a bank, dump the whole thing every turn |
| `always_inject` | maintain a bank, always surface its latest entry |
| `injection_only` | no bank; a generic nudge after a failure |

## Run it

Offline (scripted agent, no key, no cost — the default):

```bash
uv run agentmem-evals                       # all conditions, all tasks
uv run agentmem-evals --task ttl_bug --condition agentmem
```

Live (real model — always pair with a spend cap):

```bash
uv run agentmem-evals --live --model-mem claude-haiku-4-5 --max-usd 5 --seeds 3
```

Output lands in `evals/report/`: `REPORT.md`, `results.json`, and a `pass_rate.png`
if you installed the plot extra (`uv pip install 'agentmem-evals[plots]'`).

## What's here

- **`longdebug_mini/tasks/`** — buggy Python repos, each with a `REQUIREMENTS`-style
  constraint and a hidden pytest verifier. Two so far (`ttl_bug`, `off_by_one`); the
  format (`task.toml` + `repo/` + `verify/`) is built to grow toward the planned ten.
- **`src/agentmem_evals/`** — the harness: task loader, conditions, runner (real temp
  repo + subprocess pytest), metrics, budget cap, report.
- **`report/`** — a committed sample of the offline output.

## Reading the offline numbers

The offline run uses a scripted agent, so it shows the pipeline working and the
memory-vs-baseline contrast — `agentmem` recovers and stays within the constraint,
`baseline` flails and violates it. It also already shows *selectivity*: `agentmem`
reaches the same pass rate as `full_bank`/`always_inject` with far fewer
interruptions. Separating the memory conditions on *quality* (does full-bank distract?
does always-inject over-nag?) needs a real model, which is what `--live` is for.

## Terminal-Bench

A subset adapter over the official Terminal-Bench harness is planned; it plugs a real
action agent into the same conditions. Not built yet.
