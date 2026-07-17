"""Tests for `agentmem init claude-code` (the settings.json installer)."""

from __future__ import annotations

import json
from pathlib import Path

from agentmem.integrations.claude_code import (
    daemon_hooks,
    daemonless_hooks,
    has_our_hooks,
    install_claude_code,
)


def test_install_defaults_to_daemonless_hooks(tmp_path: Path) -> None:
    settings_path, created = install_claude_code(str(tmp_path))

    assert created is True
    assert (tmp_path / ".agentmem").is_dir()
    assert settings_path == tmp_path / ".claude" / "settings.json"

    hooks = json.loads(settings_path.read_text())["hooks"]
    cmd = hooks["PostToolUse"][0]["hooks"][0]["command"]
    assert cmd == "agentmem hook post-tool"  # no daemon, no curl


def test_daemon_mode_writes_curl_hooks(tmp_path: Path) -> None:
    settings_path, _ = install_claude_code(str(tmp_path), port=9000, daemon=True)
    cmd = json.loads(settings_path.read_text())["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
    assert "/hook/post-tool" in cmd
    assert "127.0.0.1:9000" in cmd


def test_install_is_idempotent(tmp_path: Path) -> None:
    install_claude_code(str(tmp_path))
    settings_path, created = install_claude_code(str(tmp_path))

    assert created is False
    hooks = json.loads(settings_path.read_text())["hooks"]
    assert len(hooks["PostToolUse"]) == 1  # not duplicated on re-run


def test_switching_modes_replaces_not_duplicates(tmp_path: Path) -> None:
    install_claude_code(str(tmp_path))  # daemon-less
    settings_path, _ = install_claude_code(str(tmp_path), daemon=True)  # switch to daemon
    commands = [
        h["command"]
        for e in json.loads(settings_path.read_text())["hooks"]["PostToolUse"]
        for h in e["hooks"]
    ]
    assert len(commands) == 1  # the daemon-less entry was dropped, not stacked
    assert "/hook/" in commands[0]


def test_install_preserves_user_settings(tmp_path: Path) -> None:
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(
        json.dumps(
            {
                "model": "sonnet",
                "hooks": {
                    "PostToolUse": [
                        {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo hi"}]}
                    ]
                },
            }
        )
    )

    install_claude_code(str(tmp_path))
    data = json.loads((claude / "settings.json").read_text())

    assert data["model"] == "sonnet"  # unrelated settings untouched
    commands = [h["command"] for e in data["hooks"]["PostToolUse"] for h in e["hooks"]]
    assert "echo hi" in commands  # the user's own hook survives
    assert "agentmem hook post-tool" in commands  # ours is added alongside


def test_has_our_hooks_detects_both_modes() -> None:
    assert has_our_hooks({"hooks": daemonless_hooks()})
    assert has_our_hooks({"hooks": daemon_hooks(8642)})
    assert not has_our_hooks({"hooks": {"PostToolUse": [{"hooks": [{"command": "echo hi"}]}]}})


def _subcommands(entries: list) -> set[str]:
    """The `hook <subcommand>` each hook in an event fires, ignoring the command prefix."""
    return {h["command"].split("hook ", 1)[1].strip() for e in entries for h in e["hooks"]}


def test_plugin_hooks_stay_in_sync_with_the_installer() -> None:
    import pytest

    plugin_path = (
        Path(__file__).parents[3] / "integrations" / "claude-code-plugin" / "hooks" / "hooks.json"
    )
    if not plugin_path.exists():
        pytest.skip("plugin not present (running outside the repo checkout)")
    plugin = json.loads(plugin_path.read_text())["hooks"]
    installer = daemonless_hooks()

    # Every memory hook the installer writes is present in the plugin, same event, same
    # subcommand, so the two install paths never drift. The plugin adds the auto-audit
    # hooks (audit-begin on SessionStart, audit-end on Stop) on top.
    for event, entries in installer.items():
        assert event in plugin
        assert _subcommands(entries) <= _subcommands(plugin[event])
    assert "Stop" in plugin and _subcommands(plugin["Stop"]) == {"audit-end"}
    assert "audit-begin" in _subcommands(plugin["SessionStart"])

    # They differ only in how they reach the engine: the plugin through its bundled
    # bootstrap wrapper, the installer through an `agentmem` already on PATH.
    plugin_cmds = [h["command"] for es in plugin.values() for e in es for h in e["hooks"]]
    installer_cmds = [h["command"] for es in installer.values() for e in es for h in e["hooks"]]
    assert all("${CLAUDE_PLUGIN_ROOT}/bin/agentmem-engine" in c for c in plugin_cmds)
    assert all(c.startswith("agentmem hook ") for c in installer_cmds)
