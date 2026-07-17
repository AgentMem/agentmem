#!/usr/bin/env python3
"""Measure what the plugin preserves across Claude Code's compaction, arm vs arm.

This drives the real claude CLI, so it spends real API credit. Everything that can
be verified without spending has been (see check_harness.py); what remains unverified
is listed in the README and checked by the first paid smoke, not assumed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[0] / "longdebug_causal"))

import grounding as G  # noqa: E402
from score import load, post_compact_metrics  # noqa: E402

PLUGIN_HOOKS = HERE.parents[1] / "integrations" / "claude-code-plugin" / "hooks" / "hooks.json"


def sh(cmd: list[str], cwd: str | None = None) -> None:
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True)


def preflight(args: argparse.Namespace) -> None:
    if not args.yes_spend:
        raise SystemExit("this run bills real API credit; pass --yes-spend to confirm")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is not set; claude in an isolated config dir needs it")
    if shutil.which("claude") is None:
        raise SystemExit("no claude binary on PATH")
    if shutil.which("agentmem") is None:
        raise SystemExit("no agentmem on PATH; the plugin hooks would silently do nothing")


def fresh_dir(path: Path) -> Path:
    if path.exists() and any(path.rglob("*")):
        raise SystemExit(f"{path} already holds an earlier run; pick a new --seed-tag")
    path.mkdir(parents=True, exist_ok=True)
    return path


def setup_arm(arm: str, seed: int, args: argparse.Namespace, spec: dict) -> dict:
    root = fresh_dir(Path(args.workroot) / f"{arm}-s{seed}")
    workdir = root / "repo"
    src = Path(spec["repo"])
    if src.exists():
        # A local fixture, not a clone: copy it and make it a git repo so ticket 4's
        # `git checkout -- .` has a committed state to revert to.
        sh(["cp", "-R", str(src.resolve()), str(workdir)])
        sh(["git", "init", "-q"], cwd=str(workdir))
        sh(["git", "add", "-A"], cwd=str(workdir))
        sh(
            ["git", "-c", "user.email=e@x", "-c", "user.name=eval", "commit", "-qm", "init"],
            cwd=str(workdir),
        )
    else:
        sh(["git", "clone", "-q", spec["repo"], str(workdir)])
        sh(["git", "checkout", "-q", spec["ref"]], cwd=str(workdir))

    config_dir = root / "claude-config"
    config_dir.mkdir(parents=True)
    # A fresh CLAUDE_CONFIG_DIR otherwise drops claude into its first-run onboarding TUI
    # and then a per-folder trust prompt, neither of which hands control back to the
    # driver. Seed the flags a finished setup leaves behind, including trust for the
    # workdir, so the session opens straight at the prompt.
    (config_dir / ".claude.json").write_text(
        json.dumps(
            {
                "hasCompletedOnboarding": True,
                "lastOnboardingVersion": "2.1.202",
                "hasSeenAutoModeEntryWarning": True,
                "numStartups": 5,
                "theme": "dark",
                "installMethod": "native",
                "projects": {
                    str(workdir.resolve()): {
                        "hasTrustDialogAccepted": True,
                        "projectOnboardingSeenCount": 1,
                        "allowedTools": [],
                        "hasClaudeMdExternalIncludesApproved": False,
                        "hasClaudeMdExternalIncludesWarningShown": False,
                    }
                },
            }
        )
    )
    if arm == "memory":
        hooks = json.loads(PLUGIN_HOOKS.read_text())
        (config_dir / "settings.json").write_text(json.dumps(hooks, indent=2))
        (workdir / "agentmem.toml").write_text(
            f'[provider]\nmodel = "{args.memory_model}"\napi_base = "{args.memory_api_base}"\n'
        )
    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = str(config_dir)
    return {"root": root, "workdir": workdir, "config_dir": config_dir, "env": env}


def find_transcript(config_dir: Path) -> Path:
    files = sorted(config_dir.glob("projects/**/*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not files:
        raise RuntimeError(f"no transcript under {config_dir}/projects")
    return files[-1]


def _turn(
    prompt: str, *, cont: bool, args: argparse.Namespace, ctx: dict
) -> subprocess.CompletedProcess:
    cmd = ["claude", "--model", args.model, "--dangerously-skip-permissions"]
    if cont:
        cmd.append("--continue")
    cmd += ["-p", prompt]
    return subprocess.run(
        cmd,
        cwd=str(ctx["workdir"]),
        env=ctx["env"],
        capture_output=True,
        text=True,
        timeout=args.ticket_timeout,
    )


def run_arm(arm: str, seed: int, args: argparse.Namespace, spec: dict) -> dict:
    ctx = setup_arm(arm, seed, args, spec)
    # Headless, not the TUI. Each ticket is a `claude -p` turn, chained with --continue
    # into one session; /compact runs the same way. Driving the real Ink TUI through a
    # pty never submitted its input reliably and a fresh config dragged in the whole
    # first-run gate cascade, while -p sidesteps both and still fires the plugin hooks.
    _turn(spec["sessions"][0], cont=False, args=args, ctx=ctx)
    for ticket in spec["sessions"][1:3]:
        _turn(ticket, cont=True, args=args, ctx=ctx)
    _turn("/compact", cont=True, args=args, ctx=ctx)
    _turn(spec["sessions"][3], cont=True, args=args, ctx=ctx)
    probe = _turn(spec["probe"], cont=True, args=args, ctx=ctx).stdout.strip()

    transcript = find_transcript(ctx["config_dir"])
    entries = load(transcript)
    return {
        "arm": arm,
        "seed": seed,
        "metrics": post_compact_metrics(entries, spec["wall_re"], spec["green_re"]),
        "probe_grounding": {
            k: v for k, v in G.score(probe, ctx["workdir"]).items() if k != "invented"
        },
        "probe": probe[:600],
        "transcript": str(transcript),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tickets", default=str(HERE / "tickets.json"))
    ap.add_argument("--arms", default="none,memory")
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--model", default="haiku")
    ap.add_argument("--memory-model", default="hosted_vllm/Qwen/Qwen3.6-27B")
    ap.add_argument("--memory-api-base", default="http://localhost:8011/v1")
    ap.add_argument("--workroot", required=True)
    ap.add_argument("--ticket-timeout", type=float, default=1800.0)
    ap.add_argument("--seed-tag", default="s1")
    ap.add_argument("--out", default="evals/report/compaction.json")
    ap.add_argument("--yes-spend", action="store_true")
    args = ap.parse_args()

    preflight(args)
    spec = json.loads(Path(args.tickets).read_text())
    out = []
    for seed in range(1, args.seeds + 1):
        for arm in [a.strip() for a in args.arms.split(",") if a.strip()]:
            print(f"== {arm} seed {seed}")
            r = run_arm(arm, seed, args, spec)
            m = r["metrics"]
            print(
                f"  wall={m['wall_reencountered']} recovered={m['recovered']} "
                f"calls_to_green={m['calls_wall_to_green']} "
                f"repeats={m['repeats_of_known_failures']} "
                f"grounded={r['probe_grounding'].get('grounded')}"
            )
            out.append(r)

    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"\nreport: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
