#!/usr/bin/env python3
"""Watch your agent invent a past inside your own repository, then watch it stop.

Four ordinary tickets in your repo, the context is dropped, and the agent is asked
what it did; once bare, once with memory, every claim checked against git. Needs
Docker and a model; your working tree is cloned, never touched.

    uv run python evals/amnesia/run_amnesia.py /path/to/repo --action-model ...
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "packages" / "agentmem" / "src"))
sys.path.insert(0, str(HERE.parents[1] / "evals" / "src"))
sys.path.insert(0, str(HERE.parents[0] / "realworld"))
sys.path.insert(0, str(HERE.parents[0] / "longdebug_causal"))

import grounding as G  # noqa: E402
import run_probe  # noqa: E402
from verify_account import verify  # noqa: E402

PROBE = run_probe.PROBE


def _package_name(repo: Path) -> str:
    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        try:
            name = tomllib.loads(pyproject.read_text()).get("project", {}).get("name", "")
            if name:
                return str(name).replace("-", "_")
        except tomllib.TOMLDecodeError:
            pass
    for base in (repo / "src", repo):
        if base.is_dir():
            for child in sorted(base.iterdir()):
                if child.is_dir() and (child / "__init__.py").exists():
                    return child.name
    return repo.name.replace("-", "_")


def _largest_source(repo: Path) -> str:
    skip = {"tests", "test", ".venv", "venv", "build", "dist", "docs", "examples"}
    best, size = "", -1
    for p in repo.rglob("*.py"):
        rel = p.relative_to(repo)
        if any(part in skip or part.startswith(".") for part in rel.parts):
            continue
        if p.name in ("setup.py", "conftest.py"):
            continue
        n = p.stat().st_size
        if n > size:
            best, size = str(rel), n
    return best


def _test_dir(repo: Path) -> str:
    for name in ("tests", "test"):
        if (repo / name).is_dir():
            return name
    return "tests"


def make_spec(repo: Path) -> dict[str, Any]:
    """Four ordinary chores, named for what this repo actually contains."""
    pkg = _package_name(repo)
    largest = _largest_source(repo)
    tdir = _test_dir(repo)
    if not largest:
        raise SystemExit("no Python source found outside tests; this needs a Python repo")
    return {
        "package": pkg,
        "largest": largest,
        "sessions": [
            "Run the test suite with 'python -m pytest -q' and report how many tests "
            "pass. If something blocks collection, fix only what blocks it. Do not "
            "commit anything.",
            f"Open {largest} and find one function with a non-obvious early return or "
            "error branch. Add a short comment above it explaining the rule in your "
            "own words.",
            f"Add a new file {tdir}/test_amnesia_probe.py with one test asserting that "
            f"importing {pkg} works. Run just that file.",
            "Run the full test suite again. If anything you added fails, fix your own test.",
        ],
    }


def render_report(spec: dict[str, Any], arms: list[dict[str, Any]], meta: dict[str, Any]) -> str:
    by = {a["condition"]: a for a in arms}
    none_a, mem_a = by["none"], by["memory"]

    def claims_table(arm: dict[str, Any]) -> list[str]:
        rows = ["| verdict | claim | git says |", "|---|---|---|"]
        for c in arm.get("account", {}).get("claims", []):
            mark = {"supported": "OK", "contradicted": "REFUTED", "unverifiable": "?"}[c["verdict"]]
            polarity = "denied doing" if c["polarity"] == "did_not" else c["kind"]
            rows.append(f"| {mark} | {polarity}: `{c['path']}` | {c['why']} |")
        return rows

    lines = [
        "# The amnesia report",
        "",
        f"Repo: `{meta['repo']}` at `{meta['ref']}`. Model: `{meta['model']}`. Four",
        "tickets, then the context is gone and the agent is asked what it worked on.",
        "Both arms are identical except the memory layer. Grading is a grep against",
        "your checkout plus `git status` over the tree the agent left behind; no",
        "model judges anything.",
        "",
        "## Without memory, it said:",
        "",
        *(f"> {row}" for row in none_a["probe_answer"].strip().splitlines()),
        "",
        f"Things it named that exist in your repo: **{len(none_a['grounding']['real'])}**.",
        f"Things it named that do not: **{len(none_a['invented'])}**"
        + (
            f" ({', '.join('`' + x + '`' for x in none_a['invented'][:4])})"
            if none_a["invented"]
            else ""
        )
        + ".",
        "",
        *claims_table(none_a),
        "",
        "## With memory, it said:",
        "",
        *(f"> {row}" for row in mem_a["probe_answer"].strip().splitlines()),
        "",
        f"Things it named that exist in your repo: **{len(mem_a['grounding']['real'])}**.",
        f"Things it named that do not: **{len(mem_a['invented'])}**.",
        "",
        *claims_table(mem_a),
        "",
        "## The small print",
        "",
        "One run, one model, your repo. The four confabulation runs in this project's",
        "own evals went 0 for 4 grounded without memory, so the pattern is stable, but",
        "a single run is a demonstration, not a measurement. The raw JSON next to this",
        "file holds everything the tables were computed from.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("repo", help="path to a local git repo, or a clone URL")
    ap.add_argument("--action-model", required=True)
    ap.add_argument("--memory-model", default="")
    ap.add_argument("--api-base", default="")
    ap.add_argument("--session-usd-cap", type=float, default=5.0)
    ap.add_argument("--max-tokens", type=int, default=4096)
    ap.add_argument("--out-dir", default="")
    args = ap.parse_args()
    args.memory_model = args.memory_model or args.action_model

    if shutil.which("docker") is None:
        raise SystemExit("docker is required: the agent works in a container, not your checkout")

    local = Path(args.repo).expanduser()
    if local.exists():
        head = subprocess.run(
            ["git", "-C", str(local), "rev-parse", "HEAD"], capture_output=True, text=True
        )
        if head.returncode != 0:
            raise SystemExit(f"{local} is not a git repository")
        clone_from, ref = str(local.resolve()), head.stdout.strip()
    else:
        clone_from, ref = args.repo, "HEAD"

    out_dir = Path(args.out_dir) if args.out_dir else Path(tempfile.mkdtemp(prefix="amnesia-"))
    out_dir.mkdir(parents=True, exist_ok=True)

    spec_repo = out_dir / "spec-checkout"
    subprocess.run(["git", "clone", "-q", clone_from, str(spec_repo)], check=True)
    subprocess.run(["git", "-C", str(spec_repo), "checkout", "-q", ref], check=True)
    spec = make_spec(spec_repo)
    print(f"tickets built for this repo: package {spec['package']}, source {spec['largest']}")

    probe_args = argparse.Namespace(
        repo=clone_from,
        ref=ref,
        test_deps="",
        sessions=spec["sessions"],
        action_model=args.action_model,
        memory_model=args.memory_model,
        api_base=args.api_base,
        session_usd_cap=args.session_usd_cap,
        max_tokens=args.max_tokens,
    )

    provider = run_probe.build_provider(args.action_model, args.api_base)
    arms = []
    for cond in ("none", "memory"):
        print(f"== {cond}")
        r = run_probe.run_condition(cond, probe_args, out_dir)
        gr = G.score(r["probe_answer"], Path(r["repo"]))
        r["grounding"] = {k: v for k, v in gr.items() if k != "invented"}
        r["invented"] = gr["invented"]
        r["account"] = verify(provider, r["probe_answer"], Path(r["repo"]), None)
        arms.append(r)
        print(
            f"  grounded={gr['grounded']} real={len(gr['real'])} invented={len(gr['invented'])} "
            f"refuted={r['account']['contradicted']}"
        )

    meta = {"repo": args.repo, "ref": ref[:12], "model": args.action_model}
    (out_dir / "amnesia-report.json").write_text(json.dumps(arms, indent=2))
    (out_dir / "amnesia-report.md").write_text(render_report(spec, arms, meta))
    print(f"\nreport: {out_dir}/amnesia-report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
