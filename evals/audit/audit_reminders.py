#!/usr/bin/env python3
"""Audit what the memory layer actually said: were its reminders right, and was its silence?"""

from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "agentmem" / "src"))

from agentmem.llm.base import LLMProvider  # noqa: E402

CITE = re.compile(r"\((P?[KP]-\d{3})\)")

VERDICT_SYSTEM = """\
You audit a memory assistant that watches a coding agent and occasionally interrupts it \
with a reminder. You are given the reminder and the memory entries it cited. Judge only \
whether the reminder is faithful to those entries and useful to an engineer.

Answer with one JSON object and nothing else:
{"faithful": true|false, "harmful": true|false, "label": "<accurate|stale|redundant|misleading>", \
"why": "<one short sentence>"}

faithful=false means the reminder asserts something its cited entries do not support.
harmful=true means acting on it would send the engineer the wrong way. A reminder that \
flags its own cited entry as out of date is accurate, not unfaithful, if the trajectory \
supports that."""


def _entries(bank: dict) -> dict:
    # archive included: the lifecycle demotes cold entries out of the live tables, so a
    # reminder from step 1 can cite an id that only survives in cold storage by the end.
    return {
        **bank.get("knowledge", {}),
        **bank.get("procedural", {}),
        **bank.get("archive", {}),
    }


def load_project_bank(mem_dir: Path) -> dict:
    """The promoted tier. PK-/PP- ids live only here, so an audit that skips it will
    accuse every project-scoped reminder of citing nothing."""
    db_path = mem_dir / "project.db"
    if not db_path.exists():
        return {}
    import sqlite3

    db = sqlite3.connect(db_path)
    try:
        rows = db.execute("SELECT * FROM sessions").fetchall()
        cols = [d[0] for d in db.execute("SELECT * FROM sessions LIMIT 1").description]
    except sqlite3.Error:
        return {}
    finally:
        db.close()
    out: dict = {}
    for row in rows:
        rec = dict(zip(cols, row, strict=False))
        for value in rec.values():
            if not isinstance(value, str) or "{" not in value:
                continue
            try:
                blob = json.loads(value)
            except json.JSONDecodeError:
                continue
            out.update(_entries(blob.get("bank", blob)))
    return out


def load_interventions(state_glob: str) -> list[dict]:
    out = []
    for tel in sorted(glob.glob(state_glob)):
        run = tel.split("/")[-3]
        mem_dir = Path(tel).parent
        bank_files = glob.glob(str(mem_dir / "banks" / "*.json"))
        bank = load_project_bank(mem_dir)
        if bank_files:
            b = json.loads(Path(bank_files[0]).read_text()).get("bank", {})
            bank.update(_entries(b))
        for line in Path(tel).read_text().splitlines():
            e = json.loads(line)
            if e.get("decision") != "inject":
                continue
            out.append(
                {
                    "run": run,
                    "step": e.get("step"),
                    "text": e.get("intervention_text") or "",
                    "cited": e.get("cited_ids") or [],
                    "bank": bank,
                }
            )
    return out


def citation_integrity(items: list[dict]) -> dict:
    """Free and deterministic: does every cited id resolve, and does every bullet cite one."""
    ghosts, uncited = [], []
    for it in items:
        shown = set(CITE.findall(it["text"]))
        if not shown:
            uncited.append(it)
        if set(it["cited"]) != shown:
            ghosts.append(it)
    return {
        "n": len(items),
        "consistent": len(items) - len(ghosts),
        "uncited": len(uncited),
        "ghosts": ghosts,
    }


def judge(provider: LLMProvider, item: dict) -> dict:
    lines, missing = [], []
    for cid in item["cited"]:
        entry = item["bank"].get(cid)
        if entry is None:
            missing.append(cid)
            continue
        lines.append(f"{cid}: {entry.get('content', '')}")
    if missing:
        # Never ask the judge to grade a reminder whose entries we failed to load:
        # it will blame the reminder for the loader's gap.
        return {
            "faithful": None,
            "harmful": None,
            "label": "unresolvable",
            "why": f"loader missed {missing}",
        }
    entries = "\n".join(lines)
    user = f"REMINDER:\n{item['text']}\n\nCITED ENTRIES:\n{entries}"
    resp = provider.complete(
        system=VERDICT_SYSTEM,
        messages=[{"role": "user", "content": user}],
        max_tokens=400,
    )
    m = re.search(r"\{.*\}", resp.text, re.S)
    if not m:
        return {"faithful": None, "harmful": None, "label": "unparsed", "why": resp.text[:80]}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {"faithful": None, "harmful": None, "label": "unparsed", "why": resp.text[:80]}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--states", required=True, help="glob for */mem/telemetry.jsonl")
    ap.add_argument("--model", default="", help="litellm/... to also judge faithfulness")
    ap.add_argument("--api-base", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    items = load_interventions(args.states)
    ci = citation_integrity(items)
    print("=== citation integrity (deterministic, no model) ===")
    print(f"  interventions:                {ci['n']}")
    print(f"  cited ids match the text:     {ci['consistent']}/{ci['n']}")
    print(f"  reminders citing nothing:     {ci['uncited']}")
    for g in ci["ghosts"][:5]:
        print(f"    MISMATCH {g['run']} step {g['step']}: claimed {g['cited']}")

    verdicts = []
    if args.model:
        from agentmem.llm.litellm import LiteLLMProvider

        provider = LiteLLMProvider(
            model=args.model.removeprefix("litellm/"),
            api_base=args.api_base or None,
            timeout=300.0,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        print(f"\n=== faithfulness ({len(items)} reminders, judged by {provider.model}) ===")
        for it in items:
            v = judge(provider, it)
            verdicts.append({**{k: it[k] for k in ("run", "step", "cited")}, **v})
            print(
                f"  {it['run']:22} step {it['step']:>2}  {str(v.get('label')):10} {v.get('why', '')[:70]}"
            )
        ok = sum(1 for v in verdicts if v.get("faithful") is True)
        harm = sum(1 for v in verdicts if v.get("harmful") is True)
        print(f"\n  faithful to cited entries: {ok}/{len(verdicts)}")
        print(f"  harmful (would mislead):   {harm}/{len(verdicts)}")

    if args.out:
        Path(args.out).write_text(
            json.dumps(
                {
                    "citation_integrity": {k: v for k, v in ci.items() if k != "ghosts"},
                    "verdicts": verdicts,
                },
                indent=2,
            )
        )
        print(f"\nreport: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
