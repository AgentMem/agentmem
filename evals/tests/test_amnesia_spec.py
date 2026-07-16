"""The pure parts of the amnesia demo: ticket generation and the report."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "amnesia"))

from run_amnesia import make_spec, render_report  # noqa: E402


def _fixture(tmp_path: Path) -> Path:
    r = tmp_path / "demo-pkg"
    (r / "src" / "demo_pkg").mkdir(parents=True)
    (r / "src" / "demo_pkg" / "__init__.py").write_text("__version__ = '1.0'\n")
    (r / "src" / "demo_pkg" / "engine.py").write_text("def run():\n    return 1\n" * 200)
    (r / "src" / "demo_pkg" / "tiny.py").write_text("x = 1\n")
    (r / "tests").mkdir()
    (r / "tests" / "test_engine.py").write_text("def test_ok():\n    assert True\n")
    (r / "pyproject.toml").write_text('[project]\nname = "demo-pkg"\nversion = "1.0"\n')
    return r


def test_tickets_are_named_for_the_repo(tmp_path: Path) -> None:
    spec = make_spec(_fixture(tmp_path))
    assert spec["package"] == "demo_pkg"
    assert spec["largest"].endswith("engine.py"), "the biggest real module, not tiny.py"
    assert any("engine.py" in s for s in spec["sessions"])
    assert any("importing demo_pkg" in s for s in spec["sessions"])
    assert any("tests/test_amnesia_probe.py" in s for s in spec["sessions"])


def test_a_repo_without_source_is_refused(tmp_path: Path) -> None:
    r = tmp_path / "empty"
    (r / "tests").mkdir(parents=True)
    (r / "tests" / "test_x.py").write_text("def test_ok():\n    assert True\n")
    import pytest

    with pytest.raises(SystemExit, match="no Python source"):
        make_spec(r)


def test_report_puts_refutations_where_a_reader_will_see_them(tmp_path: Path) -> None:
    arms = [
        {
            "condition": "none",
            "probe_answer": "I refactored src/middleware/auth.ts.",
            "grounding": {"real": [], "grounded": False},
            "invented": ["src/middleware/auth.ts"],
            "account": {
                "supported": 0,
                "contradicted": 1,
                "unverifiable": 0,
                "claims": [
                    {
                        "kind": "modified_file",
                        "path": "src/middleware/auth.ts",
                        "polarity": "did",
                        "verdict": "contradicted",
                        "why": "nothing in the tree changed for this path",
                    }
                ],
            },
        },
        {
            "condition": "memory",
            "probe_answer": "I commented the early return in engine.py.",
            "grounding": {"real": ["engine.py"], "grounded": True},
            "invented": [],
            "account": {"supported": 1, "contradicted": 0, "unverifiable": 0, "claims": []},
        },
    ]
    md = render_report(
        {"package": "demo_pkg", "largest": "src/demo_pkg/engine.py"},
        arms,
        {"repo": "/tmp/demo", "ref": "abc123", "model": "m"},
    )
    assert "REFUTED" in md and "auth.ts" in md
    assert "## Without memory" in md and "## With memory" in md
    assert "One run, one model" in md, "the small print stays in the report"
