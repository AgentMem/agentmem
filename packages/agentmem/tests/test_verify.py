"""The flight recorder verifies an account against the repo, treating the agent as an
untrusted witness. These pin the split between what the checkout confirms and what it
contradicts, and the CLI's non-zero exit on a clear fabrication."""

from __future__ import annotations

from pathlib import Path

from agentmem.cli import main
from agentmem.verify import verify_account


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "core.py").write_text("def process_value():\n    return None\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_options.py").write_text("from click.testing import CliRunner\n")
    return tmp_path


def test_real_claims_verify(tmp_path: Path) -> None:
    r = verify_account("I edited `core.py` and read `tests/test_options.py`.", _repo(tmp_path))
    assert r.grounded
    assert r.status == "VERIFIED"
    assert "core.py" in r.verified
    assert not r.contradicted


def test_invented_claims_are_contradicted(tmp_path: Path) -> None:
    r = verify_account(
        "I built `services/file_processor.py` and `utils/sanitization.py`.", _repo(tmp_path)
    )
    assert r.status == "CONTRADICTED"
    assert not r.verified
    assert "services/file_processor.py" in r.contradicted


def test_mixed_account(tmp_path: Path) -> None:
    r = verify_account("I changed `core.py` and `nope/fake.py`.", _repo(tmp_path))
    assert r.status == "MIXED"
    assert "core.py" in r.verified
    assert "nope/fake.py" in r.contradicted


def test_markdown_and_html_render(tmp_path: Path) -> None:
    r = verify_account("I made `jobs/upload_worker.py`.", _repo(tmp_path))
    md = r.to_markdown()
    assert "flight recorder" in md.lower()
    assert "contradicted" in md
    assert "jobs/upload_worker.py" in md
    html = r.to_html()
    assert html.startswith("<!doctype html>")
    assert "jobs/upload_worker.py" in html
    assert "CONTRADICTED" in html  # the status badge


def test_cli_report_grounded_exits_zero(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    code = main(["report", "--account", "I edited `core.py`.", "--repo", str(_repo(tmp_path))])
    assert code == 0
    assert "flight recorder" in capsys.readouterr().out.lower()


def test_cli_report_fabrication_exits_nonzero(tmp_path: Path) -> None:
    code = main(["report", "--account", "I built `services/x_pipeline.py`.", "--repo", str(_repo(tmp_path))])
    assert code == 1


def test_cli_report_writes_html(tmp_path: Path) -> None:
    out = tmp_path / "fr.html"
    main(["report", "--account", "I edited `core.py`.", "--repo", str(_repo(tmp_path)), "--html", str(out)])
    assert out.exists()
    assert out.read_text().startswith("<!doctype html>")
