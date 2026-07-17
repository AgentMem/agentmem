"""The ``agentmem`` command."""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

from . import __version__

if TYPE_CHECKING:
    from .verify.receipt import ActionReceipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agentmem",
        description="A proactive memory layer for long-horizon coding agents.",
    )
    parser.add_argument("--version", action="version", version=f"agentmem {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_demo = sub.add_parser("demo", help="watch the memory layer catch a repeated failure")
    p_demo.add_argument(
        "--live",
        action="store_true",
        help="use a real model for the memory agent (needs ANTHROPIC_API_KEY)",
    )

    p_replay = sub.add_parser("replay", help="pretty-print a telemetry JSONL file")
    p_replay.add_argument("path", help="path to a telemetry.jsonl file")

    p_receipts = sub.add_parser(
        "receipts", help="per-session summary of what memory did: steps, edits, reminders"
    )
    p_receipts.add_argument(
        "--state-dir", default=".agentmem", help="where the layer keeps its state"
    )

    p_bank = sub.add_parser("bank", help="inspect stored memory banks")
    p_bank.add_argument("--store", default="json", help="store spec (default: json)")
    p_bank.add_argument("--state-dir", default=".agentmem", help="state directory")
    p_bank.add_argument("--session", help="show one session's bank in full")
    p_bank.add_argument(
        "--graph", action="store_true", help="with --session, show only the causal edges"
    )
    p_bank.add_argument(
        "--tier",
        choices=["session", "project"],
        default="session",
        help="which memory tier to inspect (default: session)",
    )

    p_init = sub.add_parser("init", help="wire AgentMem into an agent harness")
    p_init.add_argument("target", choices=["claude-code"], help="which harness to set up")
    p_init.add_argument(
        "--daemon",
        action="store_true",
        help="use a long-running daemon instead of the default daemon-less hooks",
    )
    p_init.add_argument("--port", type=int, default=8642, help="daemon port (with --daemon)")
    p_init.add_argument("--cwd", default=".", help="project directory to set up")

    p_serve = sub.add_parser("serve", help="run the Claude Code daemon")
    p_serve.add_argument("--port", type=int, default=8642)
    p_serve.add_argument("--host", default="127.0.0.1")

    p_doctor = sub.add_parser("doctor", help="check the setup: key, model, hooks, daemon")
    p_doctor.add_argument("--port", type=int, default=8642, help="daemon port to probe")
    p_doctor.add_argument("--cwd", default=".", help="project directory to check")
    p_doctor.add_argument("--state-dir", default=".agentmem", help="state directory")

    # The daemon-less path: Claude Code command hooks call `agentmem hook <event>`,
    # reading the event JSON on stdin and printing any additionalContext on stdout.
    p_hook = sub.add_parser("hook", help="handle a Claude Code hook event (reads JSON on stdin)")
    p_hook.add_argument(
        "event",
        choices=[
            "session-start",
            "prompt",
            "post-tool",
            "pre-compact",
            "session-end",
            "audit-begin",
            "audit-end",
        ],
    )

    # Internal: the detached memory-step a hook spawns. Hidden from help.
    p_step = sub.add_parser("_step", help=argparse.SUPPRESS)
    p_step.add_argument("session")
    p_step.add_argument("--state-dir", default=".agentmem")
    p_step.add_argument("--tool-failure", action="store_true")

    p_report = sub.add_parser(
        "report", help="verify an agent's account of its work against a repo (flight recorder)"
    )
    src = p_report.add_mutually_exclusive_group(required=True)
    src.add_argument("--account", help="the agent's account of what it did")
    src.add_argument("--account-file", help="read the account from a file")
    p_report.add_argument("--repo", default=".", help="repository checkout to verify against")
    p_report.add_argument("--html", help="also write a self-contained HTML report to this path")

    p_audit = sub.add_parser(
        "audit",
        help="record and verify what an agent actually did against the real diff, and undo it",
    )
    p_audit.add_argument(
        "action",
        choices=["begin", "end", "undo", "show", "verify-chain"],
        help="begin a span, end+verify it, undo it, show a receipt, or check the chain",
    )
    p_audit.add_argument("--repo", default=".", help="the working tree to audit")
    p_audit.add_argument("--id", help="receipt id (defaults to the span in progress)")
    p_audit.add_argument("--claim", help="the agent's account of what it did (for end)")
    p_audit.add_argument("--claim-file", help="read the claim from a file (for end)")
    p_audit.add_argument(
        "--check",
        action="append",
        default=[],
        metavar="CMD",
        help="a command that must pass, e.g. 'pytest -q'; repeatable (for end)",
    )
    p_audit.add_argument(
        "--fail-on",
        choices=["trust", "any", "none"],
        default="trust",
        help="what makes end exit non-zero: trust breaks (default), any issue, or never",
    )
    p_audit.add_argument(
        "--git",
        action="store_true",
        help="also record git branches, commits, and tags (on begin; end auto-detects)",
    )
    p_audit.add_argument(
        "--actor", default="agent", help="who did this work, for a shared multi-actor ledger"
    )

    p_ledger = sub.add_parser(
        "ledger", help="the shared, multi-actor feed of what agents did on this project"
    )
    p_ledger.add_argument("--repo", default=".", help="the working tree whose ledger to read")
    p_ledger.add_argument("--actor", help="only this actor's entries")
    p_ledger.add_argument("--verdict", help="only entries with this verdict (e.g. FABRICATED)")
    p_ledger.add_argument("--limit", type=int, help="show at most this many, newest first")
    p_ledger.add_argument("--html", help="write the feed as a self-contained HTML page")
    p_ledger.add_argument(
        "--verify",
        action="store_true",
        help="check the chain's integrity and exit non-zero if broken",
    )

    args = parser.parse_args(argv)

    if args.command == "demo":
        return _cmd_demo(args)
    if args.command == "replay":
        return _cmd_replay(args)
    if args.command == "receipts":
        return _cmd_receipts(args)
    if args.command == "bank":
        return _cmd_bank(args)
    if args.command == "init":
        return _cmd_init(args)
    if args.command == "serve":
        return _cmd_serve(args)
    if args.command == "doctor":
        return _cmd_doctor(args)
    if args.command == "hook":
        return _cmd_hook(args)
    if args.command == "_step":
        return _cmd_step(args)
    if args.command == "report":
        return _cmd_report(args)
    if args.command == "audit":
        return _cmd_audit(args)
    if args.command == "ledger":
        return _cmd_ledger(args)

    parser.print_help()
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .verify import verify_account

    account = args.account if args.account is not None else Path(args.account_file).read_text()
    report = verify_account(account, Path(args.repo))
    print(report.to_markdown())
    if args.html:
        Path(args.html).write_text(report.to_html())
        print(f"html: {args.html}")
    # a clear fabrication (nothing verified, something contradicted) exits non-zero, so
    # `agentmem report` can gate a script or CI on the agent not inventing its own past.
    return 1 if report.status == "CONTRADICTED" else 0


def _cmd_audit(args: argparse.Namespace) -> int:
    import subprocess
    from pathlib import Path

    from .verify.receipt import Check, ReceiptStore
    from .verify.recorders import GitRecorder

    repo = Path(args.repo)
    store = ReceiptStore(repo / ".agentmem")

    if args.action == "begin":
        recorders = [GitRecorder(repo)] if args.git else []
        new_id = store.begin(repo, recorders=recorders)
        extra = " (files + git)" if args.git else ""
        print(f"recording started, receipt {new_id}{extra}")
        print('do the work, then:  agentmem audit end --claim "..."')
        return 0

    receipt_id = args.id or store.latest_id()
    if not receipt_id:
        print("no receipt id, and no span in progress (run: agentmem audit begin)", file=sys.stderr)
        return 2

    if args.action == "end":
        if args.claim is not None:
            claim = args.claim
        elif args.claim_file:
            claim = Path(args.claim_file).read_text()
        else:
            print("end needs --claim or --claim-file", file=sys.stderr)
            return 2
        checks = []
        for cmd in args.check:
            proc = subprocess.run(cmd, shell=True, cwd=repo, capture_output=True, text=True)  # noqa: S602
            out = (proc.stdout + proc.stderr).strip()
            checks.append(
                Check(name=cmd, ok=proc.returncode == 0, detail=out.splitlines()[-1] if out else "")
            )
        recorders = [GitRecorder(repo)] if "git" in store.recorded_names(receipt_id) else []
        receipt = store.end(
            receipt_id, claim, repo, recorders=recorders, checks=checks, actor=args.actor
        )
        print(receipt.to_markdown())
        return _audit_exit(receipt, args.fail_on)

    if args.action == "show":
        print(store.load(receipt_id).to_markdown())
        return 0

    if args.action == "undo":
        result = store.undo(receipt_id, repo)
        print(
            f"undo {receipt_id}: restored {len(result.restored)}, "
            f"removed {len(result.removed)}, skipped {len(result.skipped)}"
        )
        for rel in result.skipped:
            print(f"  could not restore (bytes not stored): {rel}")
        return 0

    if args.action == "verify-chain":
        problems = store.verify_chain()
        if not problems:
            print("chain intact: every receipt hashes to its seal and links to the last")
            return 0
        for p in problems:
            print(f"BROKEN: {p}", file=sys.stderr)
        return 1

    return 0


def _audit_exit(receipt: ActionReceipt, fail_on: str) -> int:
    """Turn a receipt into an exit code so `end` can gate CI. 'trust' fails only on the
    clear-cut trust breaks (fabrication, silent failure); 'any' fails on overreach too."""
    if fail_on == "none":
        return 0
    issues = set(receipt.issues)
    if fail_on == "any":
        return 1 if issues else 0
    return 1 if issues & {"fabrication", "silent-failure"} else 0


def _cmd_ledger(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .verify.ledger import Ledger

    ledger = Ledger(Path(args.repo) / ".agentmem")
    if args.verify:
        problems = ledger.verify()
        if not problems:
            print("ledger intact: every receipt hashes to its seal and links to the last")
            return 0
        for problem in problems:
            print(f"BROKEN: {problem}", file=sys.stderr)
        return 1
    filters = {"actor": args.actor, "verdict": args.verdict, "limit": args.limit}
    print(ledger.to_markdown(**filters))
    if args.html:
        Path(args.html).write_text(ledger.to_html(**filters))
        print(f"html: {args.html}")
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    from ._demo import run_demo

    return run_demo(live=args.live)


def _cmd_receipts(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .receipts import render, summarize
    from .telemetry import read_events

    path = Path(args.state_dir) / "telemetry.jsonl"
    if not path.exists():
        print(f"no telemetry at {path}; nothing has run here, or telemetry is off")
        return 1
    print(render(summarize(read_events(path))))
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .telemetry import format_replay, read_events

    path = Path(args.path)
    if not path.exists():
        print(f"No such telemetry file: {path}", file=sys.stderr)
        return 1
    events = read_events(path)
    if not events:
        print("(telemetry file is empty)")
        return 0
    print(format_replay(events))
    n_inject = sum(1 for e in events if e.get("decision") == "inject")
    print(
        f"\n{len(events)} steps, {n_inject} interventions ({n_inject / len(events):.0%} of steps)."
    )
    return 0


def _cmd_bank(args: argparse.Namespace) -> int:
    if args.tier == "project":
        return _cmd_bank_project(args)

    from .store import open_store

    store = open_store(args.store, args.state_dir)
    try:
        if args.session:
            bank = store.load_bank(args.session)
            if bank is None:
                print(f"No bank for session {args.session!r}.", file=sys.stderr)
                return 1
            if args.graph:
                if not bank.edges:
                    print("(no causal edges)")
                else:
                    for edge in bank.edges:
                        print(edge.render())
                return 0
            print(bank.render_full())
            return 0

        sessions = store.list_sessions()
        if not sessions:
            print("No sessions stored yet.")
            return 0
        print(f"{len(sessions)} session(s):\n")
        for s in sessions:
            print(f"  {s.session_id}  {s.updated_at}  {s.task[:60]}")
        print("\nShow one with:  agentmem bank --session <id>")
        return 0
    finally:
        store.close()


def _cmd_bank_project(args: argparse.Namespace) -> int:
    """The project tier is one bank per project directory, not keyed by session."""
    from .store import SqliteStore

    store = SqliteStore(f"{args.state_dir}/project.db")
    try:
        bank = store.load_bank("project")
        if bank is None or bank.is_empty():
            print("No project-tier memory yet.")
            return 0
        if args.graph:
            if not bank.edges:
                print("(no causal edges)")
            else:
                for edge in bank.edges:
                    print(edge.render())
            return 0
        print(bank.render_full())
        return 0
    finally:
        store.close()


def _cmd_init(args: argparse.Namespace) -> int:
    from .integrations.claude_code import install_claude_code

    settings_path, created = install_claude_code(args.cwd, port=args.port, daemon=args.daemon)
    verb = "Created" if created else "Updated"
    print(f"{verb} {settings_path}")
    if args.daemon:
        port_flag = f" --port {args.port}" if args.port != 8642 else ""
        print(f"Wired warm-mode hooks to a daemon on http://127.0.0.1:{args.port}.")
        print(f"\nNext:  agentmem serve{port_flag}   (needs: pip install 'agentmem-core[daemon]')")
    else:
        print("Wired daemon-less hooks (they call `agentmem hook`). Nothing to keep running.")
        print("\nJust make sure ANTHROPIC_API_KEY is set.")
    print("Then:  agentmem doctor   (verify the key, hooks, and model)")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    # The daemon lives in the separate agentmem-daemon package; import it lazily so
    # the core CLI works without FastAPI/uvicorn installed.
    try:
        import uvicorn
        from agentmem_daemon import create_app
    except ModuleNotFoundError:
        print(
            "The daemon lives in a separate package. Install it with:\n"
            "  pip install agentmem-daemon    (or, in a checkout: uv sync)",
            file=sys.stderr,
        )
        return 1

    from .config import AgentMemConfig
    from .llm import preflight

    for problem in preflight(AgentMemConfig()):
        print(f"WARNING: {problem}. Memory will run but every step will fail.", file=sys.stderr)

    print(f"AgentMem daemon on http://{args.host}:{args.port}  (Ctrl-C to stop)")
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")
    return 0


def _cmd_doctor(args: argparse.Namespace) -> int:
    from .config import AgentMemConfig
    from .llm import preflight

    print("AgentMem doctor\n")

    config = AgentMemConfig(state_dir=args.state_dir)
    problems = preflight(config)
    provider_ok = not problems
    _row(provider_ok, "model/key", f"{config.model} is reachable" if provider_ok else problems[0])

    hooks_ok, hooks_detail, daemon_mode = _hooks_status(args.cwd)
    _row(hooks_ok, "hooks", hooks_detail)

    if daemon_mode:
        daemon_ok, daemon_detail = _daemon_status(args.port)
        _row(daemon_ok, "daemon", daemon_detail)
    else:
        _row(True, "daemon", "not needed (daemon-less hooks)")

    # Only the provider check is universal; hooks/daemon are Claude-Code-only, so a
    # missing one is advice, not an error. The exit code gates on the provider.
    print()
    if provider_ok:
        print("Ready. (Anything marked [!!] above is optional setup with a hint.)")
    else:
        print("Not ready: fix the [!!] model/key line above.")
    return 0 if provider_ok else 1


def _row(ok: bool, label: str, detail: str) -> None:
    mark = "[ok]" if ok else "[!!]"
    print(f"  {mark}  {label:<8}  {detail}")


def _hooks_status(cwd: str) -> tuple[bool, str, bool]:
    """Returns (installed, detail, daemon_mode). daemon_mode is True only when the
    installed hooks are the curl-to-daemon variant, so doctor knows whether to probe."""
    import json
    from pathlib import Path

    from .integrations.claude_code import has_our_hooks

    settings = Path(cwd) / ".claude" / "settings.json"
    if not settings.exists():
        return False, "no .claude/settings.json  (run: agentmem init claude-code)", False
    try:
        data = json.loads(settings.read_text())
    except (OSError, ValueError):
        return False, f"could not read {settings}", False
    if not has_our_hooks(data):
        return False, "not installed  (run: agentmem init claude-code)", False
    daemon_mode = "/hook/" in json.dumps(data)  # curl-to-daemon commands contain it
    mode = "daemon" if daemon_mode else "daemon-less"
    return True, f"installed, {mode} mode", daemon_mode


def _daemon_status(port: int) -> tuple[bool, str]:
    import json
    import urllib.request

    url = f"http://127.0.0.1:{port}/health"
    try:
        with urllib.request.urlopen(url, timeout=1.5) as resp:  # noqa: S310 (localhost only)
            data = json.loads(resp.read())
        return True, f"up on http://127.0.0.1:{port}  (version {data.get('version', '?')})"
    except Exception:
        return False, f"not reachable on http://127.0.0.1:{port}  (run: agentmem serve)"


def _cmd_hook(args: argparse.Namespace) -> int:
    # A hook must never break the session, so anything unexpected returns empty JSON.

    print(_handle_hook(args))
    return 0


def _handle_hook(args: argparse.Namespace) -> str:
    import json
    from pathlib import Path

    from . import hookrunner
    from .config import AgentMemConfig
    from .integrations.claude_code import hook_output, project_key

    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {}

        cwd = str(payload.get("cwd") or ".")

        # Auto-audit is a separate concern from memory: it records the real diff of the
        # session and checks the agent's wrap-up against it. Keyed per conversation.
        if args.event in ("audit-begin", "audit-end"):
            return _handle_audit(args.event, cwd, payload)

        config = AgentMemConfig(state_dir=str(Path(cwd) / ".agentmem"))
        session_id = project_key(cwd)

        context: str | None = None
        event_name = ""
        if args.event == "session-start":
            context, event_name = hookrunner.on_session_start(config, session_id), "SessionStart"
        elif args.event == "prompt":
            context = hookrunner.on_prompt(config, session_id, str(payload.get("prompt") or ""))
            event_name = "UserPromptSubmit"
        elif args.event == "post-tool":
            name = str(payload.get("tool_name") or payload.get("toolName") or "tool")
            tool_input = payload.get("tool_input", payload.get("toolInput"))
            tool_response = payload.get("tool_response", payload.get("toolResponse"))
            context = hookrunner.on_post_tool(config, session_id, name, tool_input, tool_response)
            event_name = "PostToolUse"
        elif args.event == "pre-compact":
            hookrunner.on_pre_compact(config, session_id)
        elif args.event == "session-end":
            hookrunner.on_session_end(config, session_id)

        return json.dumps(hook_output(event_name, context))
    except Exception:
        return "{}"


def _audit_slot(payload: dict[str, object]) -> str:
    """A per-conversation receipt id, so each session gets its own chained receipt."""
    import re

    raw = str(payload.get("session_id") or payload.get("cwd") or "default")
    return "cc-" + re.sub(r"[^A-Za-z0-9]+", "-", raw).strip("-")[:60]


def _last_assistant_text(transcript_path: object) -> str:
    """The agent's final message from a Claude Code transcript, used as the claim. Defensive
    about the JSONL shape, and returns empty if it cannot be read."""
    import json
    from pathlib import Path

    if not transcript_path:
        return ""
    path = Path(str(transcript_path))
    if not path.exists():
        return ""
    text = ""
    for line in path.read_text(errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        message = obj.get("message") if isinstance(obj.get("message"), dict) else obj
        is_assistant = obj.get("type") == "assistant" or message.get("role") == "assistant"
        if not is_assistant:
            continue
        content = message.get("content")
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts = [
                b.get("text", "")
                for b in content
                if isinstance(b, dict) and b.get("type") == "text"
            ]
            joined = "\n".join(p for p in parts if p)
            if joined:
                text = joined
    return text


def _handle_audit(event: str, cwd: str, payload: dict[str, object]) -> str:
    from pathlib import Path

    from .verify.receipt import ReceiptStore
    from .verify.recorders import GitRecorder

    root = Path(cwd)
    store = ReceiptStore(root / ".agentmem")
    slot = _audit_slot(payload)

    if event == "audit-begin":
        store.begin(root, recorders=[GitRecorder(root)], receipt_id=slot)
        return "{}"

    claim = _last_assistant_text(payload.get("transcript_path"))
    if not claim:
        return "{}"
    recorders = [GitRecorder(root)] if "git" in store.recorded_names(slot) else []
    try:
        receipt = store.end(slot, claim, root, recorders=recorders, actor="claude-code")
    except (OSError, ValueError):
        return "{}"  # no matching begin this session, nothing to verify
    if receipt.verdict != "FAITHFUL":
        print(
            f"AgentMem: the wrap-up did not match the diff ({receipt.verdict}). "
            f"See it with:  agentmem audit show --id {slot}",
            file=sys.stderr,
        )
    return "{}"


def _cmd_step(args: argparse.Namespace) -> int:
    # The detached memory-step. It has no console, so route logs to a file: a failure
    # (bad key, provider error) lands in .agentmem/agentmem.log instead of vanishing.
    import logging
    from pathlib import Path

    from . import hookrunner
    from .config import AgentMemConfig

    log_path = Path(args.state_dir) / "agentmem.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(log_path)
    handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s"))
    log = logging.getLogger("agentmem")
    log.addHandler(handler)
    log.setLevel(logging.INFO)

    try:
        hookrunner.run_step_cold(
            AgentMemConfig(state_dir=args.state_dir),
            args.session,
            bypass_cooldown=args.tool_failure,
        )
    except Exception:
        log.exception("detached memory-step failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
