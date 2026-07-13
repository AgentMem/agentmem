#!/usr/bin/env python3
"""LLM-judge prompts + deterministic scorers for LongDebug-Causal §7.

Repo location: evals/longdebug_causal/judge_prompts.py
Companion to TASKS.md §7 and gold/CT-0X.yaml (which this module loads and
validates, the YAMLs are the normative grading truth; the snippets inside
TASKS.md are illustrative sketches).

Philosophy: DETERMINISTIC FIRST. Everything that can be a regex or a string
gate runs without any model call (keyword gate, repeated-cause detection,
stale-reminder counting, edge-relation pre-check). The LLM judge is reserved
for the two genuinely semantic calls:

  J1  root-cause postmortem grading      -> metric 2 (root-cause-identification)
  J2  causal-edge concept matching       -> metric 5 pre-screen ONLY
                                            (a human still audits the 30-edge
                                             sample; J2 just drafts the sheet)

Judge model guidance: Haiku, temperature 0, one retry on unparseable output,
then flag for manual grading rather than guessing.

The module is stdlib-only at import time; PyYAML is imported lazily inside
load_gold(). Plug in any LLM through the tiny Judge protocol, e.g.:

    class HaikuJudge:                       # adapter over the package provider
        def __init__(self, provider):       # agentmem.llm.LLMProvider
            self.p = provider
        def complete(self, prompt: str) -> str:
            return self.p.complete(model="claude-haiku-4-5", prompt=prompt,
                                   max_tokens=8, temperature=0)

CLI:
    python judge_prompts.py --validate gold/     # schema-check every yaml
    python judge_prompts.py --selftest           # no-LLM fixture tests
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

REL_ENUM = {"caused_by", "fixed_by", "rules_out", "blocks", "verifies", "supersedes"}

DEFAULT_WRAPUP_QUESTION = (
    "Before the last task: in 2-3 sentences, what was the root cause of the "
    "main failure in this project, and what was the actual fix?"
)

# Gold schema


@dataclass
class RepeatPattern:
    pattern: str
    label: str
    from_session: int = 1
    _rx: re.Pattern = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._rx = re.compile(self.pattern, re.M)


@dataclass
class GoldEdge:
    src: str
    rel: str
    dst: str


@dataclass
class StaleReminderSpec:
    from_session: int
    patterns: list[str]
    exclude_patterns: list[str] = field(default_factory=list)


@dataclass
class GoldSpec:
    task_id: str
    name: str
    relations_under_test: list[str]
    root_cause_gold: str
    gold_fix_gold: str
    required_keywords: list[str]
    gold_cause_signature: str
    gold_edges: list[GoldEdge]
    min_keyword_matches: int = 1
    forbidden_shallow: list[str] = field(default_factory=list)
    recurrence_signatures: list[str] = field(default_factory=list)
    symptom_first_session: int = 1
    repeat_patterns: list[RepeatPattern] = field(default_factory=list)
    early_root_fix_note: str = ""
    stale_reminder: StaleReminderSpec | None = None
    wrapup_question: str = DEFAULT_WRAPUP_QUESTION

    def all_signatures(self) -> list[re.Pattern]:
        return [re.compile(s) for s in [self.gold_cause_signature, *self.recurrence_signatures]]


def load_gold(path: Path) -> GoldSpec:
    """Load + validate one gold yaml. Raises ValueError with an actionable message."""
    import yaml  # lazy: keeps module import stdlib-only

    raw = yaml.safe_load(Path(path).read_text())
    problems: list[str] = []

    def need(key: str):
        if key not in raw:
            problems.append(f"missing key: {key}")
        return raw.get(key)

    for k in (
        "task_id",
        "name",
        "root_cause_gold",
        "gold_fix_gold",
        "required_keywords",
        "gold_cause_signature",
        "gold_edges",
        "relations_under_test",
    ):
        need(k)

    edges = []
    for i, e in enumerate(raw.get("gold_edges", []) or []):
        rel = e.get("rel")
        if rel not in REL_ENUM:
            problems.append(f"gold_edges[{i}].rel invalid: {rel!r} (allowed: {sorted(REL_ENUM)})")
        if not e.get("src") or not e.get("dst"):
            problems.append(f"gold_edges[{i}] needs non-empty src and dst")
        edges.append(GoldEdge(src=e.get("src", ""), rel=rel or "", dst=e.get("dst", "")))

    for r in raw.get("relations_under_test", []) or []:
        if r not in REL_ENUM:
            problems.append(f"relations_under_test invalid: {r!r}")

    for key in ("gold_cause_signature", *(raw.get("recurrence_signatures") or [])):
        pat = raw.get("gold_cause_signature") if key == "gold_cause_signature" else key
        try:
            re.compile(pat)
        except re.error as ex:
            problems.append(f"bad regex {pat!r}: {ex}")

    repeats = []
    for i, rp in enumerate(raw.get("repeat_patterns") or []):
        try:
            repeats.append(
                RepeatPattern(
                    rp["pattern"], rp.get("label", f"repeat-{i}"), int(rp.get("from_session", 1))
                )
            )
        except (KeyError, re.error) as ex:
            problems.append(f"repeat_patterns[{i}] invalid: {ex}")

    stale = None
    if raw.get("stale_reminder"):
        sr = raw["stale_reminder"]
        try:
            stale = StaleReminderSpec(
                int(sr["from_session"]), list(sr["patterns"]), list(sr.get("exclude_patterns", []))
            )
            for p in stale.patterns + stale.exclude_patterns:
                re.compile(p)
        except (KeyError, re.error) as ex:
            problems.append(f"stale_reminder invalid: {ex}")

    if problems:
        raise ValueError(f"{path}: " + "; ".join(problems))

    return GoldSpec(
        task_id=raw["task_id"],
        name=raw["name"],
        relations_under_test=list(raw["relations_under_test"]),
        root_cause_gold=raw["root_cause_gold"].strip(),
        gold_fix_gold=raw["gold_fix_gold"].strip(),
        required_keywords=list(raw["required_keywords"]),
        min_keyword_matches=int(raw.get("min_keyword_matches", 1)),
        forbidden_shallow=list(raw.get("forbidden_shallow", [])),
        gold_cause_signature=raw["gold_cause_signature"],
        recurrence_signatures=list(raw.get("recurrence_signatures", [])),
        symptom_first_session=int(raw.get("symptom_first_session", 1)),
        repeat_patterns=repeats,
        gold_edges=edges,
        early_root_fix_note=raw.get("early_root_fix_note", ""),
        stale_reminder=stale,
        wrapup_question=raw.get("wrapup_question", DEFAULT_WRAPUP_QUESTION),
    )


# Judge plumbing


class Judge(Protocol):
    def complete(self, prompt: str) -> str: ...


@dataclass
class FixtureJudge:
    """Canned replies for CI / self-test, no live model."""

    replies: list[str]
    calls: list[str] = field(default_factory=list)

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        if not self.replies:
            raise RuntimeError("FixtureJudge exhausted")
        return self.replies.pop(0)


def parse_score(raw: str) -> float | None:
    """Extract the first number and snap to {0, 0.5, 1}; None if unusable."""
    m = re.search(r"-?\d+(?:\.\d+)?", raw or "")
    if not m:
        return None
    v = float(m.group())
    for target in (0.0, 0.5, 1.0):
        if (
            abs(v - target) <= 0.1
        ):  # tight: off-rubric replies (0.7, 0.3...) are rejected, not guessed
            return target
    return None


# J1, root-cause postmortem judge (metric 2)

ROOT_CAUSE_JUDGE_PROMPT = """You are grading a debugging postmortem written by a coding agent.

TASK GOLD (true root cause):
{root_cause}

TASK GOLD (correct fix):
{gold_fix}

SHALLOW-FIX EVIDENCE LIST (signals of patching the symptom instead of the cause):
{shallow}

AGENT ANSWER (postmortem):
{answer}

FINAL DIFF SUMMARY (what the agent actually changed):
{diff}

Scoring rules:
- 1.0  the answer names the true root-cause MECHANISM (not merely the symptom,
       the failing test, or the location of the fix).
- 0.5  partially correct, OR the mechanism is evident only in the diff while
       the written answer stays at symptom level.
- 0.0  wrong, vague, or symptom-only.
- If the answer or diff shows shallow-fix evidence from the list above and the
  mechanism is NOT named, the score is capped at 0.5.
Reply with exactly one number and nothing else: 0, 0.5, or 1.
"""


@dataclass
class RootCauseResult:
    keyword_passed: bool
    matched_keywords: list[str]
    judge_score: float | None  # None => unparseable twice -> manual grading
    identified: bool  # metric 2 verdict
    judge_raw: str = ""
    needs_manual: bool = False


def keyword_gate(answer: str, gold: GoldSpec) -> tuple[bool, list[str]]:
    low = (answer or "").lower()
    hits = [k for k in gold.required_keywords if k.lower() in low]
    return len(hits) >= gold.min_keyword_matches, hits


def score_root_cause(
    gold: GoldSpec, answer: str, diff_summary: str, judge: Judge
) -> RootCauseResult:
    kw_ok, hits = keyword_gate(answer, gold)
    prompt = ROOT_CAUSE_JUDGE_PROMPT.format(
        root_cause=gold.root_cause_gold,
        gold_fix=gold.gold_fix_gold,
        shallow="\n".join(f"- {s}" for s in gold.forbidden_shallow) or "- (none)",
        answer=(answer or "").strip() or "(empty)",
        diff=(diff_summary or "").strip() or "(empty)",
    )
    raw = judge.complete(prompt)
    score = parse_score(raw)
    if score is None:  # one strict retry, then hand off to a human
        raw = judge.complete(prompt + "\nReply with exactly one number: 0, 0.5, or 1.")
        score = parse_score(raw)
    identified = bool(kw_ok and score is not None and score >= 0.5)
    return RootCauseResult(kw_ok, hits, score, identified, raw, needs_manual=score is None)


# J2, causal-edge concept matching (metric 5 PRE-SCREEN; human audits)

EDGE_MATCH_PROMPT = """You are pre-screening causal-memory edges produced by an agent against gold edges.

GOLD EDGES (concepts, not exact wording):
{gold_edges}

CANDIDATE EDGE from a run (entry ids differ across runs; compare MEANING):
  src: {src}
  rel: {rel}
  dst: {dst}

Rules:
- The relation must be IDENTICAL to count as a match (already pre-checked).
- A concept match means src and dst describe the same underlying facts as a
  gold edge, regardless of wording, ids, or level of detail.
- Direction matters: src->dst must align with the gold edge's src->dst.
Reply with exactly one integer and nothing else: the number of the matching
gold edge, or 0 if none match.
"""


@dataclass
class EdgeMatch:
    candidate: dict
    gold_index: int | None  # 1-based; None = no match
    skipped_llm: bool = False  # deterministic rel pre-check short-circuited
    judge_raw: str = ""


def prescreen_edge(gold: GoldSpec, candidate: dict, judge: Judge) -> EdgeMatch:
    """candidate = {"src": <entry text>, "rel": <relation>, "dst": <entry text>}"""
    rel = candidate.get("rel", "")
    same_rel = [(i + 1, e) for i, e in enumerate(gold.gold_edges) if e.rel == rel]
    if not same_rel:  # relation absent from gold -> no LLM call needed
        return EdgeMatch(candidate, None, skipped_llm=True)
    listing = "\n".join(f"  {i}. [{e.rel}] src: {e.src}\n      dst: {e.dst}" for i, e in same_rel)
    raw = judge.complete(
        EDGE_MATCH_PROMPT.format(
            gold_edges=listing, src=candidate.get("src", ""), rel=rel, dst=candidate.get("dst", "")
        )
    )
    m = re.search(r"\d+", raw or "")
    idx = int(m.group()) if m else 0
    valid = {i for i, _ in same_rel}
    return EdgeMatch(candidate, idx if idx in valid else None, judge_raw=raw)


def prescreen_edges(gold: GoldSpec, candidates: list[dict], judge: Judge) -> list[dict]:
    """Draft the human-audit sheet (metric 5). Returns CSV-ready rows; the
    'gold_match' column is a PROPOSAL, a human confirms/overrides before the
    edge-precision number goes anywhere near the M8 DoD."""
    rows = []
    for c in candidates:
        m = prescreen_edge(gold, c, judge)
        rows.append(
            {
                "task": gold.task_id,
                "src": c.get("src", ""),
                "rel": c.get("rel", ""),
                "dst": c.get("dst", ""),
                "gold_match": m.gold_index or 0,
                "auto_reason": "rel-not-in-gold" if m.skipped_llm else "judge",
                "human_verdict": "",  # filled by the auditor: ok / wrong / unsure
            }
        )
    return rows


# Metric 3, repeated-cause-failure (deterministic)


@dataclass
class SessionRecord:
    session: int
    diff: str  # unified diff of workspace changes this session
    hidden_output: str  # per-session hidden verifier snapshot output
    fix_attempted: bool | None = None  # None -> inferred (non-empty diff at/after symptom)


@dataclass
class RepeatHit:
    session: int
    label: str
    evidence: str


@dataclass
class RateResult:
    recurrences: int
    opportunities: int
    hits: list[RepeatHit]

    @property
    def rate(self) -> float | None:
        return None if self.opportunities == 0 else self.recurrences / self.opportunities


def infer_fix_attempted(rec: SessionRecord, gold: GoldSpec) -> bool:
    if rec.fix_attempted is not None:
        return rec.fix_attempted
    return bool(rec.diff.strip()) and rec.session >= gold.symptom_first_session


def detect_repeats(diff_text: str, gold: GoldSpec, session: int) -> list[RepeatHit]:
    hits = []
    for rp in gold.repeat_patterns:
        if session >= rp.from_session:
            m = rp._rx.search(diff_text or "")
            if m:
                hits.append(RepeatHit(session, rp.label, m.group()[:120]))
    return hits


def repeated_cause_rate(records: list[SessionRecord], gold: GoldSpec) -> RateResult:
    """§7 metric 3. Opportunity = every session strictly after the FIRST fix
    attempt. Recurrence in an opportunity session = the gold signature fires
    again in that session's hidden snapshot, OR the diff re-attempts an action
    covered by repeat_patterns (the ruled-out / known-cause list)."""
    records = sorted(records, key=lambda r: r.session)
    sigs = gold.all_signatures()
    first_fix = next((r.session for r in records if infer_fix_attempted(r, gold)), None)
    hits: list[RepeatHit] = []
    opportunities = 0
    if first_fix is None:
        return RateResult(0, 0, hits)
    for r in records:
        if r.session <= first_fix:
            continue
        opportunities += 1
        sig_hit = any(s.search(r.hidden_output or "") for s in sigs)
        pat_hits = detect_repeats(r.diff, gold, r.session)
        if sig_hit:
            hits.append(RepeatHit(r.session, "signature-recurred", gold.gold_cause_signature))
        hits.extend(pat_hits)
        # a session counts once toward the rate even if multiple evidences hit
    recur_sessions = {h.session for h in hits}
    return RateResult(len(recur_sessions), opportunities, hits)


# Metric 6, stale-reminder count (CT-05; deterministic)


@dataclass
class StaleHit:
    session: int
    step: int
    excerpt: str


def count_stale_reminders(injections: list[dict], gold: GoldSpec) -> list[StaleHit]:
    """injections = [{"session": int, "step": int, "text": str}] from telemetry.
    Hit = reminder at/after stale_reminder.from_session matching any pattern
    and NO exclude pattern (so 'the 0.26 pin is obsolete, remove it' does not
    count against the memory agent)."""
    if gold.stale_reminder is None:
        return []
    spec = gold.stale_reminder
    pats = [re.compile(p, re.I) for p in spec.patterns]
    excl = [re.compile(p, re.I) for p in spec.exclude_patterns]
    hits = []
    for inj in injections:
        if inj.get("session", 0) < spec.from_session:
            continue
        text = inj.get("text", "")
        if any(p.search(text) for p in pats) and not any(e.search(text) for e in excl):
            hits.append(StaleHit(inj.get("session", 0), inj.get("step", -1), text[:160]))
    return hits


# CLI: --validate / --selftest


def validate_dir(gold_dir: Path) -> int:
    bad = 0
    files = sorted(gold_dir.glob("CT-*.yaml"))
    if not files:
        print(f"no CT-*.yaml under {gold_dir}")
        return 1
    for f in files:
        try:
            g = load_gold(f)
            print(
                f"ok   {f.name}: {len(g.gold_edges)} gold edges, "
                f"{len(g.repeat_patterns)} repeat patterns, "
                f"{len(g.required_keywords)} keywords"
                + (", stale-reminder spec" if g.stale_reminder else "")
            )
        except Exception as e:  # noqa: BLE001, report every file
            bad += 1
            print(f"FAIL {f.name}: {e}")
    return 0 if bad == 0 else 1


def _selftest() -> int:
    g = GoldSpec(
        task_id="CT-XX",
        name="fixture",
        relations_under_test=["caused_by"],
        root_cause_gold="import-time lock binds first loop",
        gold_fix_gold="lazy per-loop lock",
        required_keywords=["event loop", "import time"],
        gold_cause_signature=r"JobTimeout",
        gold_edges=[
            GoldEdge("batch timeout", "caused_by", "module-level lock"),
            GoldEdge("timeout hypothesis", "rules_out", "batch timeout"),
        ],
        repeat_patterns=[RepeatPattern(r"timeout_s\s*=\s*[1-9]\d+", "timeout-bump", 3)],
        symptom_first_session=2,
        stale_reminder=StaleReminderSpec(4, [r"0\.26"], [r"obsolete|remove"]),
    )
    ok = True

    # parse_score robustness
    ok &= parse_score("1") == 1.0 and parse_score(" 0.5 because...") == 0.5
    ok &= parse_score("Score: 0.0") == 0.0 and parse_score("great job!") is None
    ok &= parse_score("0.7") is None  # off-rubric numbers are not snapped

    # keyword gate
    ok &= keyword_gate("the Event Loop binding at import time", g)[0]
    ok &= not keyword_gate("we increased the timeout", g)[0]

    # J1 happy path + retry path
    r = score_root_cause(
        g, "lock created at import time binds the first event loop", "diff", FixtureJudge(["1.0"])
    )
    ok &= r.identified and r.judge_score == 1.0
    r = score_root_cause(g, "event loop import time", "d", FixtureJudge(["hmm", "0.5"]))
    ok &= r.identified and r.judge_score == 0.5
    r = score_root_cause(g, "event loop import time", "d", FixtureJudge(["??", "??"]))
    ok &= (not r.identified) and r.needs_manual

    # J2: rel pre-check short-circuits without an LLM call
    fj = FixtureJudge(["should never be consumed"])
    m = prescreen_edge(g, {"src": "x", "rel": "fixed_by", "dst": "y"}, fj)
    ok &= m.gold_index is None and m.skipped_llm and not fj.calls
    m = prescreen_edge(
        g,
        {"src": "the batch job times out", "rel": "caused_by", "dst": "LOCK made at module import"},
        FixtureJudge(["1"]),
    )
    ok &= m.gold_index == 1

    # metric 3: opportunity/recurrence accounting
    recs = [
        SessionRecord(2, "fix attempt diff", "JobTimeout"),  # first fix (symptom session)
        SessionRecord(3, "+timeout_s = 30", "JobTimeout ... FAILED"),  # sig + pattern -> 1 session
        SessionRecord(4, "", "all green"),  # clean opportunity
    ]
    rr = repeated_cause_rate(recs, g)
    ok &= rr.opportunities == 2 and rr.recurrences == 1 and rr.rate == 0.5

    # metric 6: exclude guard
    inj = [
        {"session": 4, "step": 9, "text": "httpx must stay at 0.26 (INC-42)"},
        {
            "session": 4,
            "step": 12,
            "text": "the 0.26 pin is obsolete; remove it from constraints.txt",
        },
        {"session": 3, "step": 2, "text": "0.26 mentioned before the upgrade ticket"},
    ]
    ok &= len(count_stale_reminders(inj, g)) == 1

    print("selftest:", "OK" if ok else "FAILED")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--validate", type=Path, metavar="GOLD_DIR")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if args.validate:
        return validate_dir(args.validate)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
