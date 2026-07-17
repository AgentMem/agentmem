"""The action receipt verifies what an agent DID against the real diff, and can undo it.
These pin the three failure modes a text check misses (fabrication, overreach, silent
failure), the undo round-trip, and the tamper-evident chain that makes the record an audit."""

from __future__ import annotations

import json
from pathlib import Path

from agentmem.cli import main
from agentmem.verify import receipt as R
from agentmem.verify.receipt import Check, Effect, ReceiptStore, Snapshot, undo, verify_run


def _write(root: Path, rel: str, txt: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(txt)
    return p


def _tree(root: Path) -> None:
    _write(root, "core.py", "def f():\n    return 1\n")
    _write(root, "util.py", "X = 1\n")


def test_effect_detects_add_modify_delete(tmp_path: Path) -> None:
    _tree(tmp_path)
    before = Snapshot.capture(tmp_path)
    _write(tmp_path, "core.py", "def f():\n    return 2\n")
    _write(tmp_path, "new.py", "N = 1\n")
    (tmp_path / "util.py").unlink()
    after = Snapshot.capture(tmp_path)
    eff = Effect.between(before, after)
    assert eff.added == ["new.py"]
    assert eff.modified == ["core.py"]
    assert eff.deleted == ["util.py"]


def test_fabrication_flagged(tmp_path: Path) -> None:
    _tree(tmp_path)
    before = Snapshot.capture(tmp_path)
    _write(tmp_path, "core.py", "def f():\n    return 2\n")
    after = Snapshot.capture(tmp_path)
    r = verify_run(before, after, "I edited `core.py` and `services/ghost.py`.")
    assert "core.py" in r.verified
    assert "services/ghost.py" in r.fabricated
    assert r.verdict == "FABRICATED"


def test_overreach_flagged_but_lockfiles_are_incidental(tmp_path: Path) -> None:
    _tree(tmp_path)
    _write(tmp_path, "uv.lock", "a\n")
    before = Snapshot.capture(tmp_path)
    _write(tmp_path, "core.py", "x\n")
    _write(tmp_path, "secret.py", "s\n")
    _write(tmp_path, "uv.lock", "b\n")
    after = Snapshot.capture(tmp_path)
    r = verify_run(before, after, "I edited `core.py`.")
    assert r.verified == ["core.py"]
    assert "secret.py" in r.overreach
    assert "uv.lock" in r.incidental and "uv.lock" not in r.overreach
    assert r.verdict == "OVERREACH"


def test_silent_failure_needs_a_success_claim(tmp_path: Path) -> None:
    _tree(tmp_path)
    before = Snapshot.capture(tmp_path)
    _write(tmp_path, "core.py", "2\n")
    after = Snapshot.capture(tmp_path)
    r = verify_run(
        before, after, "fixed core.py, all tests pass", checks=[Check(name="pytest", ok=False)]
    )
    assert r.verdict == "SILENT_FAILURE"
    r2 = verify_run(before, after, "poked at core.py", checks=[Check(name="pytest", ok=False)])
    assert not r2.silent_failure  # a failing check without a success claim is not a lie


def test_faithful(tmp_path: Path) -> None:
    _tree(tmp_path)
    before = Snapshot.capture(tmp_path)
    _write(tmp_path, "core.py", "2\n")
    after = Snapshot.capture(tmp_path)
    r = verify_run(before, after, "edited core.py", checks=[Check(name="pytest", ok=True)])
    assert r.verdict == "FAITHFUL"
    assert not r.issues


def test_undo_round_trip(tmp_path: Path) -> None:
    _tree(tmp_path)
    before = Snapshot.capture(tmp_path, store=tmp_path / ".store")
    _write(tmp_path, "core.py", "CHANGED\n")
    _write(tmp_path, "new.py", "N\n")
    after = Snapshot.capture(tmp_path)
    r = verify_run(before, after, "edited core.py and new.py")
    res = undo(r, before, tmp_path)
    assert (tmp_path / "core.py").read_text() == "def f():\n    return 1\n"
    assert not (tmp_path / "new.py").exists()
    assert "core.py" in res.restored and "new.py" in res.removed


def test_large_file_is_not_reversible(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(R, "_MAX_BLOB", 5)
    _write(tmp_path, "big.py", "0123456789\n")
    before = Snapshot.capture(tmp_path, store=tmp_path / ".store")
    _write(tmp_path, "big.py", "now different and still over the cap\n")
    after = Snapshot.capture(tmp_path)
    r = verify_run(before, after, "edited big.py")
    assert r.reversible is False
    assert "big.py" in undo(r, before, tmp_path).skipped


def test_tamper_breaks_the_seal(tmp_path: Path) -> None:
    _tree(tmp_path)
    before = Snapshot.capture(tmp_path)
    _write(tmp_path, "core.py", "2\n")
    after = Snapshot.capture(tmp_path)
    r = verify_run(before, after, "edited core.py")
    assert not r.tampered()
    assert r.model_copy(update={"claim": "I did something else entirely"}).tampered()


def test_store_chains_receipts_and_detects_edits(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _tree(root)
    st = ReceiptStore(tmp_path / ".agentmem")

    rid = st.begin(root)
    _write(root, "core.py", "2\n")
    rec = st.end(rid, "edited core.py")
    assert rec.verdict == "FAITHFUL"
    assert st.verify_chain() == []

    rid2 = st.begin(root)
    _write(root, "core.py", "3\n")
    rec2 = st.end(rid2, "edited core.py")
    assert rec2.prev_hash == rec.hash  # each receipt links to the one before
    assert st.verify_chain() == []

    receipt_json = tmp_path / ".agentmem" / "receipts" / rid / "receipt.json"
    data = json.loads(receipt_json.read_text())
    data["claim"] = "hacked after the fact"
    receipt_json.write_text(json.dumps(data))
    assert st.verify_chain()  # non-empty: the edit is caught


def test_cli_audit_gate_fails_on_fabrication(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    _tree(tmp_path)
    assert main(["audit", "begin", "--repo", str(tmp_path)]) == 0
    _write(tmp_path, "core.py", "2\n")
    code = main(
        ["audit", "end", "--repo", str(tmp_path), "--claim", "I edited `ghost/missing.py`."]
    )
    assert code == 1
    out = capsys.readouterr().out
    assert "FABRICATED" in out or "MIXED" in out  # ghost fabricated + core.py undisclosed


def test_cli_audit_faithful_then_undo(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    _tree(tmp_path)
    main(["audit", "begin", "--repo", str(tmp_path)])
    _write(tmp_path, "core.py", "2\n")
    assert main(["audit", "end", "--repo", str(tmp_path), "--claim", "edited core.py"]) == 0
    capsys.readouterr()
    assert main(["audit", "undo", "--repo", str(tmp_path)]) == 0
    assert (tmp_path / "core.py").read_text() == "def f():\n    return 1\n"


def test_markdown_and_html_render(tmp_path: Path) -> None:
    _tree(tmp_path)
    before = Snapshot.capture(tmp_path)
    _write(tmp_path, "core.py", "2\n")
    _write(tmp_path, "x.py", "1\n")
    after = Snapshot.capture(tmp_path)
    r = verify_run(before, after, "I edited `core.py` and `ghost.py`")
    md = r.to_markdown()
    assert "Agent action receipt" in md
    assert "core.py" in md
    h = r.to_html()
    assert h.startswith("<!doctype html>")
    assert "Action receipt" in h


def test_action_audit_detection_eval_is_perfect() -> None:
    # Keep the detection scorecard honest in CI: every labeled issue caught, no false alarm.
    import subprocess
    import sys

    repo = Path(__file__).resolve().parents[3]
    proc = subprocess.run(
        [sys.executable, str(repo / "evals" / "action_audit" / "run.py")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_auto_audit_hook_records_and_verifies(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    # The Claude Code auto-audit: SessionStart snapshots, Stop reads the agent's final
    # message off the transcript and verifies it against the real diff, all through
    # `agentmem hook`. A per-conversation receipt lands in the store.
    import io

    from agentmem.verify.receipt import ReceiptStore

    _tree(tmp_path)
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "I edited `core.py` and `services/ghost.py`."}
                    ],
                },
            }
        )
        + "\n"
    )

    def feed(payload: dict) -> None:
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))

    feed({"cwd": str(tmp_path), "session_id": "s1"})
    assert main(["hook", "audit-begin"]) == 0

    _write(tmp_path, "core.py", "2\n")  # the "work" the agent did this session

    feed({"cwd": str(tmp_path), "session_id": "s1", "transcript_path": str(transcript)})
    assert main(["hook", "audit-end"]) == 0

    receipt = ReceiptStore(tmp_path / ".agentmem").load("cc-s1")
    assert "services/ghost.py" in receipt.fabricated
    assert receipt.verdict == "FABRICATED"
