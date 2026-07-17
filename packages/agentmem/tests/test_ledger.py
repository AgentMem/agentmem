"""The multi-actor ledger: several actors' receipts interleave in one hash-chained record,
and the feed reads it back. These pin that the chain links across actors, that filters and
the summary work, that the feed renders, and that concurrent ends do not fork the chain."""

from __future__ import annotations

import threading
from pathlib import Path

from agentmem.cli import main
from agentmem.verify import Ledger, ReceiptStore


def _write(root: Path, rel: str, txt: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(txt)


def _span(store: ReceiptStore, root: Path, claim: str, actor: str, content: str) -> object:
    rid = store.begin(root)
    _write(root, "f.py", content)
    return store.end(rid, claim, root, actor=actor)


def test_multi_actor_shared_chain(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write(root, "f.py", "0\n")
    store = ReceiptStore(tmp_path / ".am")

    r1 = _span(store, root, "alice edited `f.py`", "alice", "1\n")
    r2 = _span(store, root, "bob edited `f.py`", "bob", "2\n")

    assert r2.prev_hash == r1.hash  # linked across actors, one shared chain
    ledger = Ledger(tmp_path / ".am")
    assert ledger.actors() == ["alice", "bob"]
    assert ledger.verify() == []
    summary = ledger.summary()
    assert summary["total"] == 2
    assert summary["by_actor"] == {"alice": 1, "bob": 1}


def test_feed_filters_by_actor_and_verdict(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write(root, "f.py", "0\n")
    store = ReceiptStore(tmp_path / ".am")

    _span(store, root, "alice edited `f.py`", "alice", "1\n")
    _span(store, root, "bob edited `f.py` and added `ghost.py`", "bob", "2\n")  # fabrication

    ledger = Ledger(tmp_path / ".am")
    assert len(ledger.receipts(actor="alice")) == 1
    fabricated = ledger.receipts(verdict="FABRICATED")
    assert len(fabricated) == 1
    assert fabricated[0].actor == "bob"
    assert ledger.receipts(limit=1)[0].actor == "bob"  # newest first


def test_feed_renders_markdown_and_html(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write(root, "f.py", "0\n")
    store = ReceiptStore(tmp_path / ".am")
    _span(store, root, "alice edited `f.py`", "alice", "1\n")

    ledger = Ledger(tmp_path / ".am")
    md = ledger.to_markdown()
    assert "Agent action ledger" in md
    assert "alice" in md
    html = ledger.to_html()
    assert html.startswith("<!doctype html>")
    assert "What your agents actually did" in html


def test_cli_ledger_and_verify(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    root = tmp_path / "repo"
    root.mkdir()
    _write(root, "f.py", "0\n")
    main(["audit", "begin", "--repo", str(root)])
    _write(root, "f.py", "1\n")
    main(["audit", "end", "--repo", str(root), "--claim", "edited `f.py`", "--actor", "alice"])
    capsys.readouterr()

    assert main(["ledger", "--repo", str(root)]) == 0
    out = capsys.readouterr().out
    assert "alice" in out and "action ledger" in out.lower()
    assert main(["ledger", "--repo", str(root), "--verify"]) == 0


def test_concurrent_ends_do_not_fork_the_chain(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _write(root, "f.py", "0\n")
    store = ReceiptStore(tmp_path / ".am")

    ids = [store.begin(root) for _ in range(5)]

    def worker(index: int, rid: str) -> None:
        _write(root, f"f{index}.py", "x\n")
        store.end(rid, f"actor {index} did f{index}.py", root, actor=f"a{index}")

    threads = [threading.Thread(target=worker, args=(i, rid)) for i, rid in enumerate(ids)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ledger = Ledger(tmp_path / ".am")
    assert ledger.summary()["total"] == 5
    assert ledger.verify() == []  # the lock kept the chain linear under concurrent ends
