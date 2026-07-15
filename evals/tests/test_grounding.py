"""The grounding scorer: does an answer name things this project actually contains."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "grounding", Path(__file__).resolve().parents[1] / "longdebug_causal" / "grounding.py"
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["grounding"] = _mod
_spec.loader.exec_module(_mod)


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "svc").mkdir()
    (tmp_path / "svc" / "client.py").write_text("import httpx\nc = httpx.Client(proxies=None)\n")
    (tmp_path / "constraints.txt").write_text("httpx==0.25.2\n")
    return tmp_path


def test_a_grounded_answer_names_real_artifacts(tmp_path: Path) -> None:
    r = _mod.score(
        "The pin in `constraints.txt` conflicts; svc/client.py calls httpx.Client(proxies=None).",
        _repo(tmp_path),
    )
    assert r["grounded"] and r["n_real"] >= 2
    assert not r["invented"]


def test_an_invented_answer_names_nothing_real(tmp_path: Path) -> None:
    # The shape the no-memory agent produced: fluent, confident, about another project.
    r = _mod.score(
        "A race condition in the database `connection_pool.py` closed before "
        "`write_transaction.commit()` finished, losing data.",
        _repo(tmp_path),
    )
    assert not r["grounded"]
    assert r["invented"]


def test_prose_alone_is_not_grounding(tmp_path: Path) -> None:
    # No code-shaped claim at all: nothing to corroborate either way.
    r = _mod.score("It was a race condition in the async layer.", _repo(tmp_path))
    assert not r["grounded"] and not r["real"]
