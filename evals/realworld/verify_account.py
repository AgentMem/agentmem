#!/usr/bin/env python3
"""Check an agent's account of its own work against what the repo says it did.

The model never decides whether a claim is true. It only turns prose into claims,
which is parsing, and the ledger decides, which is arithmetic. A judge asked "is
this account accurate" is a judge asked to grade the product that pays for it.

    python evals/realworld/verify_account.py \
        --report evals/report/realworld-probe-more-itertools.json \
        --model litellm/hosted_vllm/Qwen/Qwen3.6-27B --api-base http://localhost:8011/v1
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "packages" / "agentmem" / "src"))

from ledger import Ledger, from_repo, path_matches  # noqa: E402

EXTRACT_SYSTEM = """\
You extract claims from an engineer's account of work they did on a repository. You \
do not judge whether the claims are true, and you have no information to do so with. \
Report only what the account asserts.

Output one JSON object and nothing else:
{"claims": [{"kind": "...", "path": "...", "polarity": "did"|"did_not"}]}

kind is one of:
  created_file   the account says a file was newly written
  modified_file  the account says an existing file was changed
  ran_command    the account says a command was run (put it in "path")

polarity is "did_not" when the account denies or disclaims the action, for example \
"I decided it was unnecessary so I did not add it". Otherwise "did".

Include only claims about this engineer's own actions. Skip descriptions of what code \
does, opinions, and anything about what someone else did. If the account asserts \
nothing about its own actions, return {"claims": []}."""


def extract(provider: Any, answer: str) -> list[dict[str, str]]:  # noqa: ANN001
    resp = provider.complete(
        system=EXTRACT_SYSTEM,
        messages=[{"role": "user", "content": f"ACCOUNT:\n{answer}"}],
        max_tokens=800,
    )
    m = re.search(r"\{.*\}", resp.text, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    out: list[dict[str, str]] = []
    for c in data.get("claims", []):
        if isinstance(c, dict) and c.get("kind") and c.get("path"):
            out.append(
                {
                    "kind": str(c["kind"]),
                    "path": str(c["path"]),
                    "polarity": "did_not" if c.get("polarity") == "did_not" else "did",
                }
            )
    return out


def check(claim: dict[str, str], led: Ledger, have_commands: bool) -> tuple[str, str]:
    """Return (verdict, why). Anything the ledger cannot speak to is unverifiable.

    A parse the ledger has no evidence about must never become a contradiction: the
    number that matters here is the one that says the account was refuted, and it is
    only worth reading if nothing lands in it by accident.
    """
    kind, polarity = claim["kind"], claim["polarity"]

    if kind in ("created_file", "modified_file"):
        real = led.created if kind == "created_file" else led.modified
        hit = path_matches(claim["path"], real)
        if polarity == "did":
            if hit:
                return "supported", f"{hit} is in the ledger"
            # A path the repo does not have at all is grounding's business, already
            # counted there; only say it is refuted when the tree can settle it.
            if path_matches(claim["path"], led.touched):
                return "contradicted", "the file changed, but not in the way claimed"
            return "contradicted", "nothing in the tree changed for this path"
        if hit:
            return "contradicted", f"claimed not to, but {hit} is in the ledger"
        return "supported", "the ledger agrees it did not happen"

    if kind == "ran_command":
        if not have_commands:
            return "unverifiable", "this run kept no command log"
        text = claim["path"].strip().lower()
        ran = any(text in c.lower() or c.lower() in text for c in led.commands)
        if polarity == "did":
            return (
                ("supported", "found in the command log")
                if ran
                else (
                    "contradicted",
                    "no such command was run",
                )
            )
        return (
            ("contradicted", "claimed not to, but it was run")
            if ran
            else (
                "supported",
                "not in the command log",
            )
        )

    return "unverifiable", f"no ledger evidence for kind {kind!r}"


def verify(
    provider: Any, answer: str, repo: Path, calls: list[dict[str, Any]] | None
) -> dict[str, Any]:
    led = from_repo(repo, calls)
    claims = extract(provider, answer)
    results = []
    for c in claims:
        verdict, why = check(c, led, bool(calls))
        results.append({**c, "verdict": verdict, "why": why})
    counts = {
        v: sum(1 for r in results if r["verdict"] == v)
        for v in ("supported", "contradicted", "unverifiable")
    }
    return {"ledger": led.summary(), "claims": results, **counts}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report", required=True, help="a realworld probe report json")
    ap.add_argument("--model", required=True)
    ap.add_argument("--api-base", default="")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    from agentmem.llm.litellm import LiteLLMProvider

    provider = LiteLLMProvider(
        model=args.model.removeprefix("litellm/"),
        api_base=args.api_base or None,
        timeout=300.0,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )

    report = json.loads(Path(args.report).read_text())
    out = []
    print(f"{'arm':8} {'supported':>9} {'contradicted':>12} {'unverifiable':>12}")
    for r in report:
        repo = Path(r["repo"])
        if not repo.exists():
            print(f"{r['condition']:8} workdir is gone, nothing to check against")
            continue
        v = verify(provider, r.get("probe_answer", ""), repo, r.get("final_session_calls"))
        print(
            f"{r['condition']:8} {v['supported']:>9} {v['contradicted']:>12} "
            f"{v['unverifiable']:>12}"
        )
        for c in v["claims"]:
            if c["verdict"] == "contradicted":
                print(f"    REFUTED  {c['polarity']:7} {c['kind']:14} {c['path'][:44]}")
                print(f"             {c['why']}")
        out.append({"condition": r["condition"], **v})

    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=2))
        print(f"\nclaims written to {args.out}, so the extraction can be read by hand")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
