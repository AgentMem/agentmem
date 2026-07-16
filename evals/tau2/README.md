# tau2-bench with a memory layer

[tau2-bench](https://github.com/sierra-research/tau2-bench) is the other benchmark the
paper reports, and its claim is +6.8pp. This runs it twice on the same tickets: tau2's
own agent, then tau2's own agent with AgentMem watching it.

Run once for real on sixteen airline tickets: 13 of 16 both arms, net zero, and no
tickets lost. See [RESULTS.md](./RESULTS.md), which is mostly about the four ways the
run failed before it worked.

## The two arms

The baseline is tau2's `llm_agent`, untouched. The memory arm is
`AgentMemLLMAgent`, which subclasses it and overrides one method. Everything the two
arms share, they share by inheritance, so a difference in the results cannot come from
a difference in the harness.

The reminder is injected for exactly one call and removed in a `finally`. tau2 grades
the trajectory, so a reminder left behind would become a message the agent was never
sent, and the grader would score it.

## Setup

tau2 needs its own virtualenv. It is not optional and not cosmetic:

- **Python 3.12, not 3.13.** Its `pyproject.toml` says `>=3.12,<3.14`, but its voice
  path imports `audioop`, which PEP 594 removed in 3.13. On 3.13, `import tau2` fails
  before anything runs. This repo is 3.11, so tau2 cannot live in it either way.
- **`pip install tau2` installs the wrong package.** The name on PyPI belongs to an
  unrelated project by another author. The benchmark exists only on GitHub.

```bash
git clone https://github.com/sierra-research/tau2-bench && cd tau2-bench
uv venv --python 3.12 .venv-tau2
VIRTUAL_ENV=$PWD/.venv-tau2 uv pip install -e . -e ../AgentMem/packages/agentmem -e ../AgentMem/evals
```

Install ours editable. Without `-e` the venv holds a copy taken at install time, so
every check below passes against whatever the code was then, including the bugs it
still had.

`evals/vm/bringup.sh` does all of this on a fresh box, along with everything else.

## Check it before renting anything

```bash
.venv-tau2/bin/python evals/tau2/check_adapter.py
```

This hands the agent to the real tau2 orchestrator and runs four tickets on the `mock`
domain with every model call stubbed. No network, no GPU, no key. It asserts what a
unit test cannot: that the agent registers, that a reminder reaches the model, that
none survives into the graded trajectory, and that what one ticket learns is in the
project bank waiting for the next.

The unit tests (`evals/tests/test_tau2_agent.py`) run in this repo's 3.11 venv against
a double of tau2, and against the real classes when pointed at the tau2 venv:

```bash
uv run pytest evals/tests/test_tau2_agent.py                       # double
.venv-tau2/bin/python -m pytest evals/tests/test_tau2_agent.py -c /dev/null   # real
```

## Run it

```bash
.venv-tau2/bin/python evals/tau2/run_live.py \
    --domain airline \
    --action-model litellm/hosted_vllm/Qwen/Qwen3.6-27B \
    --api-base http://localhost:8000/v1 --no-thinking \
    --out tau2-airline.json
```

`--api-base` routes the agent, the user simulator and the memory layer to the same
self-hosted endpoint, which is what makes the run cost nothing per token. The runner
says so at startup, and says the opposite if a hosted model is in the mix.

## Three things that will bite

**One session for the run, not one per ticket.** Promotion is what lets ticket N+1 use
what ticket N learned, and an entry only becomes eligible once its bank has seen
`continual_min_sessions_lived` (3) ticket boundaries. That counter lives on the bank. A
session per ticket gives every ticket a fresh bank whose counter starts at zero, so
nothing is ever eligible. The arm still injects, the reminders are still grounded,
every ticket still works, and the project bank stays empty for the entire run.

**The ticket boundary belongs to the runner, not the agent.** tau2 scores a ticket
after the conversation ends, so `stop` cannot know what the ticket was worth. Ending
the ticket there means ending it at a reward of zero, a zero reward moves no
reinforcement, and an entry with no reinforcement is never promoted. The memory arm
therefore runs `run_single_task` per ticket and hands the real score back before the
next one starts, which is also why it cannot use tau2's batch runner.

**`advantage_enabled` is off by default and reinforcement lives behind it.** With it
off, entries never gain reinforcement, so nothing is promoted, so the project bank is
empty. `run_live.py` turns it on. Anything else driving this layer for a multi-session
run should too.

The memory arm runs one ticket at a time, and the runner forces this. Two tickets at
once would interleave two conversations into one bank, and the order notes were learned
in is the thing being measured. Parallelism belongs in separate shards with separate
state dirs.

## What to expect

An earlier draft of this section predicted a null on the grounds that tau2 tickets are
single conversations, like the Terminal-Bench tasks that already came out flat. That
reasoning was wrong and is worth leaving here as a correction. Terminal-Bench tasks
are unrelated to each other, so memory has nothing to carry between them and the null
is structural. A tau2 domain is fifty tickets against the same policy, the same tools
and the same schema, which is exactly the setting this layer is built for.

So the honest position is that the outcome is unknown, which is the only good reason
to run anything. What tempers it: the domain policy is already in every ticket's
system prompt, so memory can only earn its place on what the policy does not say.
