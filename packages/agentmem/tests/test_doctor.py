"""`agentmem doctor` turns an invisible misconfiguration into a readable checklist."""

from __future__ import annotations

from pathlib import Path

import pytest
from agentmem.cli import main


def test_doctor_flags_a_missing_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rc = main(["doctor", "--cwd", str(tmp_path), "--state-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "[!!]" in out
    assert "ANTHROPIC_API_KEY" in out


def test_doctor_passes_with_key_and_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    main(["init", "claude-code", "--cwd", str(tmp_path)])  # writes .claude/settings.json
    capsys.readouterr()  # drop the init output

    rc = main(["doctor", "--cwd", str(tmp_path), "--state-dir", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0  # provider is fine; the daemon being down doesn't fail the check
    assert "[ok]  model/key" in out
    assert "[ok]  hooks" in out
