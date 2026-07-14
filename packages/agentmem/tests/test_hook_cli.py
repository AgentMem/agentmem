"""`agentmem hook <event>`: reads the Claude Code event JSON on stdin, prints any
additionalContext on stdout, and never crashes the session on bad input."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from agentmem.cli import main
from agentmem.integrations.claude_code import project_key
from agentmem.schemas import MemoryBank, MemoryEntry
from agentmem.store import open_store


def _feed(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(text))


def test_session_start_is_empty_json_with_no_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _feed(monkeypatch, json.dumps({"cwd": str(tmp_path)}))
    rc = main(["hook", "session-start"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "{}"


def test_session_start_recaps_a_seeded_bank(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    session_id = project_key(str(tmp_path))
    store = open_store("json", str(tmp_path / ".agentmem"))
    store.save_bank(
        session_id,
        "fix",
        MemoryBank(
            knowledge={
                "K-001": MemoryEntry(
                    id="K-001",
                    kind="knowledge",
                    tag="task",
                    content="keep the public API stable",
                    created_step=1,
                    updated_step=1,
                )
            }
        ),
    )
    store.close()

    _feed(monkeypatch, json.dumps({"cwd": str(tmp_path)}))
    rc = main(["hook", "session-start"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "additionalContext" in out and "K-001" in out


def test_hook_survives_garbage_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _feed(monkeypatch, "not json at all")
    rc = main(["hook", "post-tool"])
    assert rc == 0
    assert capsys.readouterr().out.strip() == "{}"
