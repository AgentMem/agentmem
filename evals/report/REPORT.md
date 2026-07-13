# AgentMem eval report

Mode **offline** · 2 tasks · 1 seed(s) · memory model `scripted`

> **Offline run.** The action agent is scripted, so these numbers show the pipeline working and the memory-vs-baseline contrast, not the finer ordering between memory conditions (which needs a real model). Run `--live` with a key and a `--max-usd` cap for that.

| Condition | pass@1 | repeated failures | requirement violations | interventions | memory tokens |
|---|---|---|---|---|---|
| `baseline` | 0% ± 0% | 5.0 | 0.5 | 0.0 | 0 |
| `injection_only` | 0% ± 0% | 5.0 | 0.5 | 6.0 | 0 |
| `full_bank` | 100% ± 0% | 1.0 | 0.0 | 7.0 | 0 |
| `always_inject` | 100% ± 0% | 1.0 | 0.0 | 7.0 | 0 |
| `agentmem` | 100% ± 0% | 1.0 | 0.0 | 1.0 | 0 |

**Takeaway:** AgentMem lifts pass@1 from 0% to 100% (Δ +100%), with 1.0 vs 5.0 repeated failures and 0.0 vs 0.5 requirement violations.
