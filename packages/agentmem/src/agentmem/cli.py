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
        choices=["session-start", "prompt", "post-tool", "pre-compact", "session-end"],
    )

    # Internal: the detached memory-step a hook spawns. Hidden from help.
    p_step = sub.add_parser("_step", help=argparse.SUPPRESS)
    p_step.add_argument("session")
    p_step.add_argument("--state-dir", default=".agentmem")
    p_step.add_argument("--tool-failure", action="store_true")

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
    if args.command == "hook":
        return _cmd_hook(args)
    if args.command == "_step":
        return _cmd_step(args)

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
            AgentMemConfig(state_dir=args.state_dir), args.session, bypass_cooldown=args.tool_failure
        )
    except Exception:
        log.exception("detached memory-step failed")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
