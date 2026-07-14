# LongDebug-Causal benchmark spec (v1.0)

> The benchmark for causal memory. Five multi-session debugging tasks where the **root cause is temporally and semantically distant from the symptom**, designed so that (a) plain context windows lose the cause across session resets, (b) semantic-similarity retrieval surfaces the wrong material, and (c) causal edges (`caused_by`, `fixed_by`, `rules_out`, `blocks`, `supersedes`) provide a measurable advantage.
> Each task exercises a **different edge relation**, together they cover the full set.

---

## 0. Shared mechanics (all tasks)

**Harness.** Reuse the LongDebug-mini runner. One Docker container per task run; the **workspace volume persists across sessions** (same checkout, on-disk state survives), the **action agent context resets every session**, the **memory bank persists**. Session cap: 15 action-turns. Conditions compared: `full` (memory, no edges) vs `full+causal` (memory with edges), ≥3 seeds each.

**Session script.** Each task defines 5-6 sessions. Each session = one ticket-style prompt given to the action agent. Tickets are deliberately realistic: some contain **plausible but misleading guidance** (mirrors real work; also tests requirement memory). Filler sessions create temporal distance and bank pressure.

**Wrap-up probe (root-cause measurement).** At the start of the final session, before the last ticket, the harness asks the action agent:
> *"Before the last task: in 2-3 sentences, what was the root cause of the main failure in this project, and what was the actual fix?"*
The answer is scored by (1) keyword gate, at least one `required_keywords` term present, and (2) LLM judge (rubric in `judge_prompts.py`) over the answer **and** the final diff. Root-cause-identification = keyword gate AND judge ≥ 0.5.

**Determinism policy.** Causal traps are tied to on-disk state + hidden verifiers, not to a specific agent path. If the agent proactively fixes the root cause early (e.g., respects REQUIREMENTS.md and never triggers the trap), the task ends early and counts as a **requirement-respected success**, that outcome is equally informative and is logged separately (`early_root_fix=true`).

**Per-session snapshot.** After every session the harness runs the hidden verifier suite and records: pass/fail per test, symptom signature (normalized top frame + exception type), and whether any `gold_cause` signature recurred. This feeds the repeated-cause-failure metric.

**Directory layout per task:**
```
evals/longdebug_causal/
├── SPEC.md                   # this file
├── judge_prompts.py          # rubric prompts
├── gold/
│   └── CT-0X.yaml            # gold edges + keywords + cause signatures
└── CT-0X_name/
    ├── repo/                 # the seeded Python project (8-15 files)
    ├── sessions.yaml         # ticket text + per-session visible test command
    ├── verifier/             # hidden pytest suite + root-cause checks (never mounted into agent workspace)
    └── Dockerfile
```

---

## 1. CT-01 `stale-artifacts`, relation under test: **`caused_by` (chain through a generated artifact)**

**Theme.** Small FastAPI-style user service with a codegen step: `schema/user.yaml` → `make generate` → `generated/models.py` + `tests/fixtures/users.json`.

**Repo tree (11 files).**
```
repo/
├── REQUIREMENTS.md            # "generated/ and tests/fixtures are DERIVED from schema/*.yaml.
│                              #  Never edit them by hand. Run `make generate` after ANY schema change.
│                              #  All tests must pass with `uv run pytest`."
├── Makefile                   # generate: python tools/codegen.py
├── schema/user.yaml
├── tools/codegen.py           # deterministic: renders models + fixtures from schema
├── generated/models.py        # STALE at t0 relative to schema (see seed)
├── app/api.py                 # list_users, get_user endpoints
├── app/serializer.py          # dict-building for API responses
├── app/storage.py             # loads tests/fixtures/users.json as the demo DB
├── tests/fixtures/users.json  # STALE at t0
├── tests/test_api.py          # visible smoke tests (pass at t0)
└── pyproject.toml
```

**Seed (pre-planted drift).** Git history contains a commit `"schema: add optional display_name to User"` that edited `schema/user.yaml` **without** running `make generate`. So `generated/models.py` and `users.json` lack `display_name`. Nothing fails at t0, no code reads the field yet.

**Session script.**

| S | Ticket (given to action agent) | Design intent |
|---|---|---|
| 1 | "Add pagination (`limit`, `offset`) to `GET /users`. Tests: `uv run pytest tests/test_api.py`." | Unrelated success. Memory agent should bank K: *generated files derive from schema via `make generate`* (from REQUIREMENTS + Makefile). |
| 2 | "Add request logging middleware; log method, path, status." | Filler. Distance + decay pressure. |
| 3 | "Expose `display_name` in the `/users` response. Note from the previous dev: the field was already added to the schema last sprint, so this should be a one-liner in the serializer." | **Trap fires.** Serializer reads `user["display_name"]` from fixture-built objects → `KeyError: 'display_name'` in hidden tests. The ticket's framing ("one-liner") plus the *semantically nearest* code (serializer edited in S3, middleware edited in S2) pull retrieval away from the true cause: **stale generated artifacts**. Correct fix: `make generate`, not defensive `.get()` hacks. |
| 4 | "QA reports `/users/{id}` 500s for some ids, investigate and fix." | Same root cause, second surface (`get_user` path). Measures repeated-cause: does the agent re-derive, or does the reminder `(P: KeyError ←caused_by← K: fixtures derive from schema; fixed_by → run make generate)` short-circuit it? A `.get()` patch in S3 makes S4 fail again → counted as repeated-cause. |
| 5 | Wrap-up probe, then: "Add optional `pronouns` field to the User schema and expose it." | **Proactivity check**, the state-changing-call intervention point: the reminder should fire *before* the schema edit ("after schema changes run make generate"). Hidden verifier asserts fixtures regenerated. |

**Hidden verifier.** Full pytest incl. `verifier/test_serializer_hidden.py` (asserts `display_name`/`pronouns` present and correct for all fixture users) + `verifier/test_fixtures_fresh.py` (hash of `users.json` == hash of codegen output, catches hand-edits, enforcing REQUIREMENTS).

**Gold (CT-01.yaml).**
```yaml
required_keywords: [make generate, codegen, regenerate, stale, fixtures, schema]
forbidden_shallow: [".get(", "defensive default"]   # judge treats these as shallow-fix evidence
gold_cause_signature: "KeyError:display_name@app/serializer.py"
gold_edges:
  - {src: "KeyError display_name in serializer tests", rel: caused_by, dst: "generated files/fixtures derive from schema via make generate; regen not run after schema commit"}
  - {src: "KeyError display_name in serializer tests", rel: fixed_by,  dst: "ran make generate to regenerate models + fixtures"}
```

**Expected failure of `full` (no causal).** Bank likely holds both the K (codegen rule) and the P (KeyError) as *flat* entries; without the edge, Phase 2 has no basis to co-select them, and S4/S5 reminders miss the derivation link.

---

## 2. CT-02 `config-drift`, relation under test: **`caused_by` (composite cause from the agent's own past actions)**

**Theme.** Batch data pipeline (CSV in → normalize → aggregate → report) with an **on-disk cache** that survives sessions (workspace volume).

**Repo tree (10 files).** `pipeline/{ingest,normalize,aggregate,report}.py`, `pipeline/cache.py` (key = sha of input path + step name, **no code-version component**), `config.toml` (`[cache] enabled = false`), `data/*.csv`, `tests/test_pipeline.py` (golden numbers), `REQUIREMENTS.md`: *"Results must be reproducible from a clean checkout. Any caching must be safe under code changes."*

**Session script.**

| S | Ticket | Design intent |
|---|---|---|
| 1 | "Pipeline is slow on repeated runs; profile and speed it up. Cache infra exists but is off." | Natural fix: set `cache.enabled=true`. Tests pass (cache cold→warm, same code). **Cause #1 planted by the agent itself.** Memory agent should bank P: *enabled cache; keys don't include code version* (the sharp-eyed bank entry this task rewards). |
| 2 | "Normalization must trim whitespace and casefold city names, update `normalize.py` + its unit tests." | **Cause #2.** Unit tests for normalize pass (they call the function directly). Cached *step outputs* from S1 are now stale. |
| 3 | "Nightly report numbers look wrong for some cities, investigate `test_aggregates` failures." | **Symptom.** Golden-number mismatches, only for inputs cached in S1. Semantic retrieval on the failing assertion points at `aggregate.py`, which contains a deliberately ugly-but-correct weighted-mean (distractor). True chain: enable cache (S1) + change normalize (S2) → stale cached step outputs → wrong aggregates. Correct fix: invalidate cache **and** make keys version-aware (satisfies REQUIREMENTS); `rm -rf .cache` alone = shallow. |
| 4 | Filler: "Add `--city` filter flag to report CLI." | Distance. |
| 5 | Wrap-up probe, then: "Casefold country names too (same treatment as cities)." | **Repeated-cause check.** Version-aware keys ⇒ passes untouched. Shallow S3 fix ⇒ stale cache again ⇒ recurrence logged. Causal reminder should fire before the normalize edit (*"code change under enabled cache previously produced stale results (P-xx caused_by P-yy)"*). |

**Hidden verifier.** Golden aggregates over full dataset + `verifier/test_cache_safety.py`: run pipeline → mutate a normalize constant → run again → outputs MUST change (proves version-aware keys or safe invalidation).

**Gold.**
```yaml
required_keywords: [cache, stale, invalidate, cache key, version]
gold_cause_signature: "AssertionError:golden-mismatch@tests/test_pipeline.py::test_aggregates"
gold_edges:
  - {src: "wrong aggregate numbers", rel: caused_by, dst: "cache enabled with keys lacking code version"}
  - {src: "wrong aggregate numbers", rel: caused_by, dst: "normalize.py logic changed after outputs were cached"}
  - {src: "wrong aggregate numbers", rel: fixed_by,  dst: "cache keys include normalizer version + one-time invalidation"}
```
**Why causal wins.** The cause is a *conjunction of two of the agent's own edits, two sessions apart*, exactly what flat similarity cannot compose. Also the primary probe for **edge-precision audits** (two `caused_by` edges must both be attributed).

---

## 3. CT-03 `ruled-out`, relation under test: **`rules_out` (hypothesis elimination across sessions)**

**Theme.** Async job worker where a deterministic-but-obscure bug is *disguised* as a timeout.

**Repo tree (12 files).** `worker/{pool,jobs,retry}.py`, `worker/config.toml` (`timeout_s = 5`, red herring), `tests/test_single.py`, `tests/test_batch.py`, mocks, etc.

**Seed.**
- `worker/pool.py` line ~8: `LOCK = asyncio.Lock()` at **module import time**.
- pytest-asyncio, function-scoped event loops. `test_single.py` acquires the lock on loop A; `test_batch.py` later acquires on loop B → `RuntimeError: ... is bound to a different event loop`. **Deterministic**, but **order-dependent** (only when batch runs after single).
- `worker/retry.py` decorator catches `RuntimeError`, retries 3×, then raises `JobTimeout("job exceeded deadline")`. → **Visible symptom is a timeout; the real error is swallowed.**

**Session script.**

| S | Ticket | Design intent |
|---|---|---|
| 1 | "Add a `priority` field to jobs; make the pool schedule high before low." | Success; both test files now share the pool path (arms the trap). |
| 2 | "`test_batch` fails with JobTimeout in CI. CI machines are slow, probably just bump the timeout." | **H1 (misleading ticket).** Bumping `timeout_s` doesn't help. A good memory agent banks P: *raising timeout did NOT fix JobTimeout* → later `rules_out` edge. Session likely ends mid-investigation at turn cap, by design. |
| 3 | "Still failing. A teammate suspects the HTTP mock is flaky, check the mock layer." | **H2.** Also wrong; second `rules_out`. The one true observable a careful agent can bank: *fails only when batch runs after single* (`pytest tests/test_batch.py` alone passes!), the pivotal P entry. |
| 4 | "Third attempt, you have full freedom. Find the real cause." | **Payoff.** `full+causal` opens with `(P-09) fails only after test_single (order-dependent); (P-05 rules_out) timeout bump ineffective; (P-07 rules_out) mock patch ineffective` → straight to import-time lock. Fix: lazy per-loop lock (or fixture-scoped). Baseline `full` frequently re-tries H1/H2 → **repeated-cause-failure** = re-attempting a ruled-out fix (timeout/mock edits detected in diff). |
| 5 | Wrap-up probe, then filler: "Add jitter to retry backoff." | Confirms no regression; probe scored. |

**Hidden verifier.** Fixed-order run (`test_single` then `test_batch`) must pass; `verifier/test_no_module_lock.py` asserts no module-level `asyncio.Lock()`/`asyncio.Event()` in `worker/` (AST check); timeout config must remain ≤ 10s (blocks the shallow "huge timeout" escape).

**Gold.**
```yaml
required_keywords: [event loop, module-level, import time, asyncio.Lock, test order, bound to a different]
gold_cause_signature: "JobTimeout@tests/test_batch.py (wrapped RuntimeError: bound to a different event loop)"
gold_edges:
  - {src: "test_batch JobTimeout", rel: caused_by, dst: "asyncio.Lock created at module import binds to first event loop"}
  - {src: "hypothesis: timeout too low", rel: rules_out, dst: "test_batch JobTimeout"}   # direction: attempt rules_out as explanation
  - {src: "hypothesis: flaky HTTP mock",  rel: rules_out, dst: "test_batch JobTimeout"}
  - {src: "test_batch JobTimeout", rel: fixed_by, dst: "lazy per-loop lock creation"}
```
**Primary metric here:** repeated-cause-failure (ruled-out retries) and time-to-fix in S4.

---

## 4. CT-04 `blast-radius`, relation under test: **`fixed_by` + `blocks` (a past fix in a shared module breaks a distant surface)**

**Theme.** CLI reporting tool + web API sharing `utils/dates.py`.

**Repo tree (11 files).** `cli/report.py`, `api/filters.py`, `utils/dates.py` (`parse_date` uses `%d/%m/%y`), `tests/test_cli.py`, `tests/test_api.py`, sample data, `REQUIREMENTS.md`: *"Date formats: CLI accepts US `mm/dd/yy`; API accepts EU `dd/mm/yy`. Shared code in `utils/` must remain format-agnostic, format handling belongs at each boundary."*

**Session script.**

| S | Ticket | Design intent |
|---|---|---|
| 1 | "CLI crashes on `04/17/25` (US format). Simplest is probably to flip the pattern in `utils/dates.py::parse_date`." | **Misleading-but-tempting ticket** that directly contradicts REQUIREMENTS. Session-1 verifier runs CLI tests only → the shared-util flip *passes*. Requirement-respecting agents fix at the CLI boundary instead (→ `early_root_fix`, S3 never breaks, logged, still success). Memory agent should bank P: *changed shared parse_date to %m/%d* + K: *both CLI and API import utils/dates*. |
| 2 | Filler: "Add `--format json` output to the CLI report." | Distance. |
| 3 | "API `/bookings?from=05/03/25` returns wrong rows for early-month dates and 400s for others, fix." | **Symptom, nasty on purpose:** for day ≤ 12 the flipped pattern *silently swaps* day/month (wrong rows, no exception); day > 12 raises. Error surfaces in `api/filters.py`, zero lexical overlap with the S1 CLI ticket. Causal reminder: `(P-04) parse_date flipped to %m/%d in S1 to fix CLI; (K-02) api/filters imports the same util` → correct fix: boundary-specific parsing, util restored format-agnostic (per REQUIREMENTS). |
| 4 | "Export a weekly digest that reuses the same date filters." | Regression pressure on the S3 fix (a CLI-side hack that re-breaks API paths recurs here → repeated-cause). |
| 5 | Wrap-up probe, then: "Add `parse_datetime` (date + HH:MM) to utils." | **Proactivity:** reminder before the state-changing edit, *shared utils stay format-agnostic (K-xx, blocks)*. Hidden verifier asserts the new function is format-parameterized. |

**Hidden verifier.** CLI tests (US), API tests (EU incl. day ≤ 12 silent-swap cases), and `verifier/test_util_agnostic.py`: `utils/dates.parse_date` must take an explicit format argument or dual-mode spec, no hardcoded regional default.

**Gold.**
```yaml
required_keywords: [utils/dates, shared, "%m/%d", format-agnostic, boundary, both CLI and API]
gold_cause_signature: "silent day/month swap + ValueError@api/filters.py"
gold_edges:
  - {src: "API wrong rows / 400s on EU dates", rel: caused_by, dst: "shared parse_date flipped to %m/%d in session 1 CLI fix"}
  - {src: "requirement: utils stay format-agnostic", rel: blocks, dst: "editing shared parse_date to a regional format"}
  - {src: "API wrong rows / 400s on EU dates", rel: fixed_by, dst: "boundary-specific formats; util takes explicit format"}
```
**Why causal wins.** Tests **abstraction transfer** (2604.27003): the useful memory is the abstract rule *"my S1 fix changed shared code both surfaces depend on"*, not the verbatim CLI traceback. Silent-wrong-data (day ≤ 12) also punishes shallow retrieval hard, there is no exception string to match.

---

## 5. CT-05 `stale-pin`, relation under test: **`supersedes` (diagnosis expires; stale reminders are harmful)**

**Theme.** Service with a dependency pinned in **two places** after an old incident.

**Repo tree (10 files).** `svc/client.py` (uses `httpx`), `requirements.txt`, **`constraints.txt`** (second pin, the buried one, left from INC-42), `scripts/setup.sh` (`pip install -r requirements.txt`, deliberately **no** `-c`; the CI workflow and the hidden clean-runner verifier DO install with `-c constraints.txt`, which is exactly what buries the second pin), `docs/DEPLOY.md` (note: *"httpx pinned to 0.26 after INC-42, 0.27 renamed the proxies argument"*), tests, REQUIREMENTS.md (*"dependency changes must keep `scripts/setup.sh` AND the CI install green"*).

**Session script.**

| S | Ticket | Design intent |
|---|---|---|
| 1 | "Fresh clones fail: `TypeError: unexpected keyword 'proxies'`. Figure out why and stabilize." | Agent discovers the 0.27 rename; pins `httpx==0.26.*` in `requirements.txt` (constraints.txt pin pre-exists, most agents won't notice). Banks K: *httpx must stay 0.26 (INC-42)* + ideally P: *pin applied in requirements.txt; constraints.txt also pins*. |
| 2-3 | Fillers: retry helper; healthcheck endpoint. | Decay distance; the K entry ages. |
| 4 | "Migrate to `httpx>=0.28`: new `proxy=` API, and remove any old pins. The 0.26 pin is obsolete as of this ticket." | **Supersession moment.** Agent updates code + requirements.txt. Hidden setup-verifier fails: constraints.txt still forces 0.26 → resolver conflict (or 0.26 installed → `TypeError: unexpected keyword 'proxy'`). Root cause: **the forgotten second pin**. Memory-side test: the S1 entry *"httpx must stay 0.26"* must be **superseded**, for `full+causal`, a `supersedes` edge + salience demotion retires it. Re-injecting it in S4/S5 is scored as a **harmful/stale reminder** (calibration failure, negative reward). |
| 5 | Wrap-up probe, then: "CI still red on a clean runner, make `scripts/setup.sh` green and prove it." | Payoff/repeat window. Reminder for `full+causal`: `(P-03) 0.26 was pinned in TWO places in S1; requirements.txt updated, constraints.txt not (K-01 superseded by K-07)`. Baseline typically burns turns re-diagnosing the version conflict from scratch, or worse, re-pins 0.26 "because the bank says so" (**repeated-cause + harmful reminder**, both logged). |

**Hidden verifier.** `verifier/test_setup.sh` in a clean venv: install must resolve, `httpx>=0.28` imported, `proxy=` call path passes; grep-check: **no** 0.26 pin remains anywhere (requirements, constraints, CI yaml).

**Gold.**
```yaml
required_keywords: [constraints.txt, second pin, supersede, obsolete, "0.26", resolver]
gold_cause_signature: "ResolutionImpossible|TypeError:proxy@scripts/setup.sh"
gold_edges:
  - {src: "K: upgrade to httpx>=0.28 (S4 ticket)", rel: supersedes, dst: "K: httpx must stay 0.26 (INC-42)"}
  - {src: "setup failure after upgrade", rel: caused_by, dst: "stale second pin in constraints.txt from the S1 stabilization"}
  - {src: "setup failure after upgrade", rel: fixed_by, dst: "removed 0.26 from constraints.txt (all pin sites)"}
```
**Unique measurement:** this is the only task where a *memory can be actively harmful*, it isolates the stale-reminder failure mode and directly tests the `supersedes` edge + salience demotion working together.

---

## 6. Coverage matrix

| Task | Edge relation exercised | Cause origin | Symptom distance | Distinct failure mode measured |
|---|---|---|---|---|
| CT-01 | `caused_by`, `fixed_by` | Pre-seeded repo drift | 2 sessions, cross-module (schema→serializer) | Missed derivation link; shallow `.get()` fix |
| CT-02 | `caused_by` (composite ×2), `fixed_by` | Agent's own edits (S1+S2) | 1-2 sessions, cross-stage (cache→aggregate) | Cannot compose two flat memories |
| CT-03 | `rules_out`, `caused_by` | Pre-seeded, disguised error | Same file, wrong hypothesis space | Re-trying eliminated hypotheses |
| CT-04 | `blocks`, `fixed_by` | Agent's own fix in shared code | 2 sessions, cross-surface (CLI→API), silent data bug | Verbatim vs abstract memory; requirement violation |
| CT-05 | `supersedes`, `caused_by` | Agent's own diagnosis, later obsolete | 3 sessions, second location | Stale/harmful reminder; supersession |

---

## 7. Scoring & metrics (wiring into `evals/report/`)

**Per-run outputs** (JSONL, one line per session + one summary line):

1. **Task pass@1**, hidden verifier suite green at end of final session.
2. **Root-cause-identification** ∈ {0, 1}, wrap-up answer passes the keyword gate AND LLM judge ≥ 0.5. Judge prompt (in `judge_prompts.py`):
   ```
   You are grading a debugging postmortem. TASK GOLD: <root cause paragraph
   from gold yaml>. AGENT ANSWER: <...>. FINAL DIFF SUMMARY: <...>.
   Score 1.0 if the answer names the true root cause mechanism (not just the
   symptom or the fix location); 0.5 if partially correct or cause named only
   in the diff; 0.0 otherwise. Shallow-fix evidence (<forbidden_shallow>)
   without the mechanism caps the score at 0.5. Reply with the number only.
   ```
3. **Repeated-cause-failure rate**, per session: `gold_cause_signature` recurs after a prior fix attempt, OR the diff re-attempts an action already covered by a `rules_out`/`caused_by` gold edge (CT-03/CT-05 pattern list in gold yaml). Reported as recurrences ÷ opportunities.
4. **Time-to-fix**, action-turns from first symptom session start to hidden-verifier green.
5. **Edge precision (full+causal only)**, sample 30 edges across runs; human label vs `gold_edges` by **concept match** (entry ids differ per run; match src/dst descriptions + relation). Target ≥ 80%.
6. **Stale-reminder count (CT-05)**, injections citing the superseded entry after S4 ticket delivery.
7. Standard LongDebug metrics carry over: tokens, wall-time, intervention stats.

**Targets.** Across CT-01..05, `full+causal` vs `full`: root-cause-id **+20pts absolute**, repeated-cause-failure **−30% relative**, no regression on plain LongDebug-mini, edge precision ≥ 80%.

## 8. Build checklist

- [ ] Scaffold the 5 `repo/` projects exactly as specified (files, seeds, git history where noted, CT-01 needs the seeded commit).
- [ ] `sessions.yaml` per task with ticket texts above verbatim (they are calibrated, including the misleading ones).
- [ ] Hidden verifiers under `verifier/`, mounted only in the harness container, never in the agent workspace.
- [ ] `gold/CT-0X.yaml` files as specified; extend `evals/report/` with metrics 2-6.
- [ ] Scaffold must satisfy the **normative anchors** declared in `smoke.py` (file paths + exact strings the canned edits grip onto, preflight-checked; `python smoke.py --list` prints them without running anything).
- [ ] Smoke-run each task with the scripted dummy agent, `python smoke.py` (no LLM calls), to prove traps fire deterministically before spending model tokens: `trap` scenario must end red with the gold signature firing at the specced session; `gold` scenario must end green.
- [ ] Budget: reuse `--max-usd`; start with memory = Haiku, 1 seed, then scale to 3 seeds.
