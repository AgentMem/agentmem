# LongRun-sim capabilities dashboard

Model `claude-haiku-4-5` · 30 sessions · est ~$0.015 (168 calls, 7320 in / 1464 out)

## The four differentiators
1. **Structured procedural memory**: 60 entries {'procedural': 60}; procedural tags {'fix': 60}.
2. **Causal memory**: 0 edges (none).
3. **Proactive intervention**: 4 injects over 30 steps; 3 on recurring-failure sessions, 1 on routine.
4. **Learned policy (advantage)**: 30 steps carried an advantage estimate, 0 gated to silence.

## Long-horizon numbers

| Metric | Result | Bar |
|---|---|---|
| Retention (no-memory baseline) | 0% | - |
| Retention (AgentMem) | 0% | ≥ 90% |
| Interference (cross-repo) | 50.0% | < 5% |
| Bank-growth ratio | 1.88 | < 1.5 |

Interference is measured on one shared bank across all three repos (the hard case); in production AgentMem scopes memory per project, so cross-repo citation is structurally near zero.

## Per-probe detail

| Probe | Fact in digest | With memory | No memory | Answer (with memory) |
|---|---|---|---|---|
| a-req-frozen-api | NO | miss | miss | <context_for_action> - recall the prior fix (P-001) </context_for_action> |
| a-req-timeout-source | NO | miss | miss | <context_for_action> - recall the prior fix (P-001) </context_for_action> |
| a-lesson-ttl | NO | miss | miss | <context_for_action> - recall the prior fix (P-001) </context_for_action> |
| b-req-cache-versioned | NO | miss | miss | <context_for_action> - recall the prior fix (P-001) </context_for_action> |
| b-req-casefold | NO | miss | miss | <context_for_action> - recall the prior fix (P-001) </context_for_action> |
| b-lesson-stale-cache | NO | miss | miss | <context_for_action> - recall the prior fix (P-001) </context_for_action> |
| c-req-single-lock | NO | miss | miss | <context_for_action> - recall the prior fix (P-001) </context_for_action> |
| c-req-httpx-pin | NO | miss | miss | <context_for_action> - recall the prior fix (P-001) </context_for_action> |
| c-lesson-retries | NO | miss | miss | <context_for_action> - recall the prior fix (P-001) </context_for_action> |
