"""Tests for `agentmem init claude-code` (the settings.json installer)."""

from __future__ import annotations

import json
from pathlib import Path

from agentmem.integrations.claude_code import default_hooks, install_claude_code, merge_settings


def test_install_creates_files(tmp_path: Path) -> None:
    settings_path, created = install_claude_code(str(tmp_path))

    assert created is True
    assert (tmp_path / ".agentmem").is_dir()
    assert settings_path == tmp_path / ".claude" / "settings.json"

    hooks = json.loads(settings_path.read_text())["hooks"]
    cmd = hooks["PostToolUse"][0]["hooks"][0]["command"]
    assert "/hook/post-tool" in cmd
    assert "127.0.0.1:8642" in cmd


def test_install_is_idempotent(tmp_path: Path) -> None:
    install_claude_code(str(tmp_path))
    settings_path, created = install_claude_code(str(tmp_path))

    assert created is False
    hooks = json.loads(settings_path.read_text())["hooks"]
    assert len(hooks["PostToolUse"]) == 1  # not duplicated on re-run


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
    assert any("/hook/post-tool" in c for c in commands)  # ours is added alongside


def test_default_hooks_use_the_given_port() -> None:
    cmd = default_hooks(port=9000)["SessionStart"][0]["hooks"][0]["command"]
    assert "127.0.0.1:9000" in cmd


def test_reinstall_on_new_port_replaces_not_duplicates() -> None:
    first = merge_settings({}, default_hooks(8642))
    second = merge_settings(first, default_hooks(9999))
    commands = [h["command"] for e in second["hooks"]["SessionStart"] for h in e["hooks"]]
    assert len(commands) == 1
    assert "9999" in commands[0]
