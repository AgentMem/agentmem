"""Translation helpers between Claude Code hook payloads and AgentMem.

These are pure functions so they can be tested without a running daemon or a real
Claude Code session. The daemon (agentmem-daemon) is a thin HTTP shell around them.

Hook payload shapes vary between Claude Code versions, so we read fields defensively
and never assume a key is present. If the shape changes, this file is the one place
to adjust.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from copy import deepcopy
from itertools import islice
from pathlib import Path
from typing import Any

from ..schemas import Event, MemoryBank, MemoryEntry


def project_key(cwd: str) -> str:
    """A stable, readable id for a project directory.

    Used as the session id so a project's bank persists across Claude Code sessions:
    same directory, same memory.
    """
    digest = hashlib.sha1(cwd.encode("utf-8")).hexdigest()[:8]
    name = re.sub(r"[^a-zA-Z0-9]+", "-", Path(cwd).name).strip("-").lower() or "project"
    return f"{name}-{digest}"


def events_from_tool_use(
    tool_name: str,
    tool_input: Any,
    tool_response: Any,
    *,
    ok: bool = True,
) -> list[Event]:
    """A tool call + its result, as two window events."""
    return [
        Event(kind="tool_call", tool_name=tool_name, text=_summarize_input(tool_name, tool_input)),
        Event(
            kind="tool_result", tool_name=tool_name, ok=ok, text=_summarize_response(tool_response)
        ),
    ]


def event_from_prompt(prompt: str) -> Event:
    return Event(kind="message", role="user", text=prompt)


def response_indicates_error(tool_response: Any) -> bool:
    """Best-effort: did a PostToolUse response actually carry a failure?

    Claude Code fires PostToolUse even when a Bash command exits non-zero, so a tool
    can 'succeed' at the harness level while failing at the task level. We sniff for
    the obvious signals; when unsure we say no (the tool-fail hook is the certain path).
    """
    if isinstance(tool_response, dict):
        for key in ("exit_code", "exitCode", "returncode"):
            code = tool_response.get(key)
            if isinstance(code, int) and code != 0:
                return True
        for key in ("error", "is_error", "isError"):
            if tool_response.get(key):
                return True
    return False


def bank_digest(
    bank: MemoryBank, max_items: int = 6, *, project: MemoryBank | None = None
) -> str | None:
    """A short recap of durable project memory for SessionStart.

    This is the cross-session hook: a new session opens already knowing the
    requirements and hard-won lessons from earlier ones. `project`, if given, is
    listed first: it's the durable, promoted-and-generalized tier, so it outranks
    whatever the last session happened to leave in its own bank. None when there's
    nothing worth recapping.
    """
    if bank.is_empty() and (project is None or project.is_empty()):
        return None

    # Highest salience first, so the cap trims the faded tail, not the newest lessons.
    def by_salience(b: MemoryBank) -> list[MemoryEntry]:
        return sorted(b.all_entries(), key=lambda e: e.lifecycle.salience, reverse=True)

    lines = ["[AgentMem] Memory from earlier sessions on this project:"]
    if project is not None and not project.is_empty():
        for entry in islice(by_salience(project), max_items):
            lines.append(f"- ({entry.id}) {entry.content}")
    for entry in islice(by_salience(bank), max_items):
        lines.append(f"- ({entry.id}) {entry.content}")
    # Surface a few high-confidence causal links; they're the cross-session payoff.
    strong = [e for e in bank.edges if e.confidence >= 0.7]
    for edge in islice(strong, 4):
        lines.append(f"- {edge.render()}")
    return "\n".join(lines)


def hook_output(event_name: str, additional_context: str | None) -> dict[str, Any]:
    """The JSON a hook returns. Empty dict means 'nothing to add'."""
    if not additional_context:
        return {}
    return {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": additional_context,
        }
    }


def _summarize_input(tool_name: str, tool_input: Any) -> str:
    if isinstance(tool_input, dict):
        # The fields worth showing depend on the tool; command and path are the
        # ones that carry signal for a memory agent.
        for key in ("command", "cmd", "file_path", "path", "query", "url"):
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return _compact_json(tool_input)
    if isinstance(tool_input, str):
        return tool_input.strip()
    return _compact_json(tool_input)


def _summarize_response(tool_response: Any) -> str:
    if isinstance(tool_response, dict):
        for key in ("stdout", "output", "content", "result", "stderr", "error"):
            value = tool_response.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return _compact_json(tool_response)
    if isinstance(tool_response, str):
        return tool_response.strip()
    return _compact_json(tool_response)


def _compact_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, default=str)[:2000]
    except (TypeError, ValueError):
        return str(value)[:2000]


# `agentmem init claude-code` writes these hooks into a project's
# .claude/settings.json. The default is daemon-less: each hook is a command that runs
# `agentmem hook <event>`, which reads the event JSON on stdin and prints any reminder.
# The --daemon variant pipes to a long-running local daemon over curl instead; its
# `|| echo '{}'` makes a hook a no-op when the daemon isn't running.

DEFAULT_PORT = 8642

# The five events AgentMem hooks, in (event, matcher) form. PostToolUse covers failures
# too (the runtime reads the tool's exit code), so there's no separate failure hook.
_EVENTS: tuple[tuple[str, str | None], ...] = (
    ("session-start", None),
    ("prompt", None),
    ("post-tool", "*"),
    ("pre-compact", None),
    ("session-end", None),
)
_EVENT_TO_HOOK = {
    "session-start": "SessionStart",
    "prompt": "UserPromptSubmit",
    "post-tool": "PostToolUse",
    "pre-compact": "PreCompact",
    "session-end": "SessionEnd",
}


def _curl(port: int, path: str) -> str:
    url = f"http://127.0.0.1:{port}/hook/{path}"
    return (
        f"curl -sS -m 5 -X POST {url} "
        f"-H 'Content-Type: application/json' --data-binary @- 2>/dev/null || echo '{{}}'"
    )


def _hook_block(command_for: Callable[[str], str]) -> dict[str, Any]:
    block: dict[str, Any] = {}
    for event, matcher in _EVENTS:
        entry: dict[str, Any] = {"hooks": [{"type": "command", "command": command_for(event)}]}
        if matcher:
            entry = {"matcher": matcher, **entry}
        block[_EVENT_TO_HOOK[event]] = [entry]
    return block


def daemonless_hooks() -> dict[str, Any]:
    """The default: command hooks that call the CLI directly, no daemon to run."""
    return _hook_block(lambda event: f"agentmem hook {event}")


def daemon_hooks(port: int = DEFAULT_PORT) -> dict[str, Any]:
    """The --daemon variant: curl the event to a long-running local daemon."""
    return _hook_block(lambda event: _curl(port, event))


def _is_ours(entry: dict[str, Any]) -> bool:
    return any(
        "agentmem hook " in cmd or ("127.0.0.1" in cmd and "/hook/" in cmd)
        for cmd in (h.get("command", "") for h in entry.get("hooks", []))
    )


def has_our_hooks(settings: dict[str, Any]) -> bool:
    """True if AgentMem's hooks are already in a .claude/settings.json dict."""
    hooks = settings.get("hooks", {})
    return any(_is_ours(e) for entries in hooks.values() for e in entries)


def merge_settings(existing: dict[str, Any], hooks: dict[str, Any]) -> dict[str, Any]:
    """Merge our hooks into a settings dict, leaving everything else alone.

    Idempotent: re-running drops any prior AgentMem entries first, so the port can
    change and hooks never pile up. The user's own hooks and other settings survive.
    """
    result = deepcopy(existing)
    result_hooks: dict[str, Any] = result.setdefault("hooks", {})
    for event, entries in hooks.items():
        kept = [e for e in result_hooks.get(event, []) if not _is_ours(e)]
        result_hooks[event] = kept + entries
    return result


def install_claude_code(
    cwd: str, port: int = DEFAULT_PORT, *, daemon: bool = False
) -> tuple[Path, bool]:
    """Create .agentmem/ and merge the hooks into .claude/settings.json.

    Default is the daemon-less command hooks; `daemon=True` writes the curl-to-daemon
    variant. Returns (settings_path, created), `created` True when settings.json was new.
    """
    root = Path(cwd)
    (root / ".agentmem").mkdir(parents=True, exist_ok=True)

    settings_path = root / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)

    created = not settings_path.exists()
    existing: dict[str, Any] = {}
    if not created:
        try:
            existing = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}

    hooks = daemon_hooks(port) if daemon else daemonless_hooks()
    merged = merge_settings(existing, hooks)
    settings_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    return settings_path, created
