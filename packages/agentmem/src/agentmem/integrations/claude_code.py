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
from copy import deepcopy
from itertools import islice
from pathlib import Path
from typing import Any

from ..schemas import Event, MemoryBank


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

    lines = ["[AgentMem] Memory from earlier sessions on this project:"]
    if project is not None and not project.is_empty():
        for entry in islice([*project.knowledge.values(), *project.procedural.values()], max_items):
            lines.append(f"- ({entry.id}) {entry.content}")
    entries = [*bank.knowledge.values(), *bank.procedural.values()]
    for entry in islice(entries, max_items):
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
# .claude/settings.json. They're command hooks that pipe the event JSON (stdin) to
# the local daemon and return its response. `|| echo '{}'` means a hook is a no-op
# when the daemon isn't running, so it can never wedge a session.

DEFAULT_PORT = 8642


def _curl(port: int, path: str) -> str:
    url = f"http://127.0.0.1:{port}/hook/{path}"
    return (
        f"curl -sS -m 5 -X POST {url} "
        f"-H 'Content-Type: application/json' --data-binary @- 2>/dev/null || echo '{{}}'"
    )


def default_hooks(port: int = DEFAULT_PORT) -> dict[str, Any]:
    """The hooks block AgentMem installs into .claude/settings.json."""

    def entry(path: str, matcher: str | None = None) -> dict[str, Any]:
        e: dict[str, Any] = {"hooks": [{"type": "command", "command": _curl(port, path)}]}
        return {"matcher": matcher, **e} if matcher else e

    # PostToolUse covers failures too: the daemon reads the exit code from the
    # response, so there's no separate failure hook to depend on.
    return {
        "SessionStart": [entry("session-start")],
        "UserPromptSubmit": [entry("prompt")],
        "PostToolUse": [entry("post-tool", matcher="*")],
        "PreCompact": [entry("pre-compact")],
        "SessionEnd": [entry("session-end")],
    }


def _is_ours(entry: dict[str, Any]) -> bool:
    return any(
        "127.0.0.1" in h.get("command", "") and "/hook/" in h.get("command", "")
        for h in entry.get("hooks", [])
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


def install_claude_code(cwd: str, port: int = DEFAULT_PORT) -> tuple[Path, bool]:
    """Create .agentmem/ and merge the hooks into .claude/settings.json.

    Returns (settings_path, created) where `created` is True when settings.json
    didn't exist before.
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

    merged = merge_settings(existing, default_hooks(port))
    settings_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    return settings_path, created
