"""The plugin manifests, and the wrapper's promise that a missing engine never breaks the session."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
PLUGIN = REPO / "integrations" / "claude-code-plugin"
MARKETPLACE = REPO / ".claude-plugin" / "marketplace.json"
WRAPPER = PLUGIN / "bin" / "agentmem-engine"

# The memory hooks and the auto-audit hooks the engine's `agentmem hook` command
# understands. The hooks.json must wire subcommands from this set, or an event fires one
# the engine will reject.
MEMORY_EVENTS = {"session-start", "prompt", "post-tool", "pre-compact", "session-end"}
AUDIT_EVENTS = {"audit-begin", "audit-end"}


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def test_marketplace_points_at_the_plugin() -> None:
    m = _load(MARKETPLACE)
    assert m["name"] == "agentmem"
    assert m["owner"]["name"] == "AgentMem"
    (entry,) = m["plugins"]
    assert entry["name"] == "agentmem"
    # source is a repo-relative subdir and it has to actually exist
    source = (REPO / entry["source"]).resolve()
    assert source == PLUGIN.resolve()
    assert (source / ".claude-plugin" / "plugin.json").is_file()


def test_plugin_manifest_matches_the_marketplace() -> None:
    p = _load(PLUGIN / ".claude-plugin" / "plugin.json")
    assert p["name"] == "agentmem"
    market = _load(MARKETPLACE)["plugins"][0]
    assert p["version"] == market["version"]  # one version, two files


def test_hooks_call_the_wrapper_with_known_events() -> None:
    hooks = _load(PLUGIN / "hooks" / "hooks.json")["hooks"]
    assert set(hooks) == {
        "SessionStart",
        "UserPromptSubmit",
        "PostToolUse",
        "PreCompact",
        "Stop",  # the auto-audit verifies the wrap-up here
        "SessionEnd",
    }
    seen = set()
    for groups in hooks.values():
        for group in groups:
            for h in group["hooks"]:
                cmd = h["command"]
                # every hook goes through the bootstrap wrapper, by plugin-root path
                assert "${CLAUDE_PLUGIN_ROOT}/bin/agentmem-engine" in cmd
                assert cmd.strip().startswith('"${CLAUDE_PLUGIN_ROOT}')  # path is quoted
                seen.add(cmd.rsplit(" ", 1)[-1])
    assert seen == MEMORY_EVENTS | AUDIT_EVENTS


def test_wrapper_is_executable_shell() -> None:
    assert WRAPPER.is_file()
    assert WRAPPER.stat().st_mode & 0o111, "wrapper must be executable"
    assert WRAPPER.read_text().startswith("#!/bin/sh")


@pytest.mark.skipif(not Path("/bin/sh").exists(), reason="needs POSIX sh")
def test_wrapper_never_breaks_the_session_when_no_engine() -> None:
    # With an empty PATH nothing (agentmem/uvx/pipx) is found. The wrapper must still
    # exit 0 with no stdout, so Claude Code injects nothing and the session continues.
    proc = subprocess.run(
        ["/bin/sh", str(WRAPPER), "hook", "session-start"],
        env={"PATH": ""},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0
    assert proc.stdout == ""
    assert "agentmem-core" in proc.stderr  # the one hint it prints


def test_setup_and_status_skills_ship() -> None:
    assert (PLUGIN / "skills" / "setup" / "SKILL.md").is_file()
    assert (PLUGIN / "skills" / "status" / "SKILL.md").is_file()
