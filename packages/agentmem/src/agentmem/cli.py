"""The ``agentmem`` command. Plain argparse, no CLI framework dependency.

demo    run the offline (or --live) demonstration
replay  pretty-print a telemetry file, step by step
bank    inspect stored memory banks
init    wire AgentMem into a harness (claude-code)
serve   run the Claude Code daemon
doctor  check the setup: key, model, hooks, daemon
"""

from __future__ import annotations

import argparse
import sys

from . import __version__


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
    p_init.add_argument("--port", type=int, default=8642, help="daemon port the hooks call")
    p_init.add_argument("--cwd", default=".", help="project directory to set up")

    p_serve = sub.add_parser("serve", help="run the Claude Code daemon")
    p_serve.add_argument("--port", type=int, default=8642)
    p_serve.add_argument("--host", default="127.0.0.1")

    p_doctor = sub.add_parser("doctor", help="check the setup: key, model, hooks, daemon")
    p_doctor.add_argument("--port", type=int, default=8642, help="daemon port to probe")
    p_doctor.add_argument("--cwd", default=".", help="project directory to check")
    p_doctor.add_argument("--state-dir", default=".agentmem", help="state directory")

    args = parser.parse_args(argv)

    if args.command == "demo":
        return _cmd_demo(args)
    if args.command == "replay":
        return _cmd_replay(args)
    if args.command == "bank":
        return _cmd_bank(args)
    if args.command == "init":
        return _cmd_init(args)
    if args.command == "serve":
        return _cmd_serve(args)
    if args.command == "doctor":
        return _cmd_doctor(args)

    parser.print_help()
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    from ._demo import run_demo

    return run_demo(live=args.live)


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

    settings_path, created = install_claude_code(args.cwd, port=args.port)
    verb = "Created" if created else "Updated"
    port_flag = f" --port {args.port}" if args.port != 8642 else ""
    print(f"{verb} {settings_path}")
    print(f"Wired Claude Code hooks to the daemon on http://127.0.0.1:{args.port}.")
    print(f"\nNext:  agentmem serve{port_flag}   (needs: pip install agentmem-daemon)")
    print("Then:  agentmem doctor   (verify the key, hooks, and daemon)")
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

    hooks_ok, hooks_detail = _hooks_status(args.cwd)
    _row(hooks_ok, "hooks", hooks_detail)

    daemon_ok, daemon_detail = _daemon_status(args.port)
    _row(daemon_ok, "daemon", daemon_detail)

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


def _hooks_status(cwd: str) -> tuple[bool, str]:
    import json
    from pathlib import Path

    from .integrations.claude_code import has_our_hooks

    settings = Path(cwd) / ".claude" / "settings.json"
    if not settings.exists():
        return False, "no .claude/settings.json  (run: agentmem init claude-code)"
    try:
        data = json.loads(settings.read_text())
    except (OSError, ValueError):
        return False, f"could not read {settings}"
    if has_our_hooks(data):
        return True, f"installed in {settings}"
    return False, "not installed  (run: agentmem init claude-code)"


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


if __name__ == "__main__":
    raise SystemExit(main())
