"""Recorders beyond files: git branches and commits, and any listable API resource."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from agentmem.verify import ApiRecorder, GitRecorder, ReceiptStore

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git on PATH")


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)


def _repo(root: Path) -> None:
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "a.py").write_text("x = 1\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "init")


def test_git_recorder_sees_a_commit_and_a_new_branch(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _repo(repo)
    rec = GitRecorder(repo)
    before = rec.capture()
    (repo / "a.py").write_text("x = 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fix the value")
    _git(repo, "branch", "feature/x")
    changes = rec.diff(before, rec.capture())
    assert any(c.kind == "commit" and c.verb == "added" for c in changes)
    branches = [c for c in changes if c.kind == "branch"]
    # only the new branch, not the default branch that moved under the commit
    assert [c.label for c in branches] == ["feature/x"]


def test_integration_unmentioned_branch_is_overreach(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _repo(repo)
    store = ReceiptStore(tmp_path / ".am")
    rid = store.begin(repo, recorders=[GitRecorder(repo)])
    (repo / "a.py").write_text("x = 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fix")
    _git(repo, "branch", "feature/x")
    r = store.end(rid, "I fixed `a.py` and committed it.", repo, recorders=[GitRecorder(repo)])
    assert "a.py" in r.verified
    assert any("feature/x" in o for o in r.overreach)
    assert r.verdict == "OVERREACH"
    assert any(c.kind == "commit" for c in r.changes)
    assert store.verify_chain() == []


def test_claimed_git_action_with_no_trace_is_fabrication(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _repo(repo)
    store = ReceiptStore(tmp_path / ".am")
    rid = store.begin(repo, recorders=[GitRecorder(repo)])
    (repo / "a.py").write_text("x = 2\n")  # edited, never committed
    r = store.end(
        rid, "I committed and pushed the fix to `a.py`.", repo, recorders=[GitRecorder(repo)]
    )
    assert "fabrication" in r.issues


def test_api_recorder_flags_and_verifies_resources(tmp_path: Path) -> None:
    store = ReceiptStore(tmp_path / ".am")
    work = tmp_path / "d"
    work.mkdir()

    resources = {"bucket-1": "v1"}
    api = ApiRecorder("cloud", lambda: dict(resources), kind="resource")
    rid = store.begin(work, recorders=[api])
    resources["bucket-2"] = "v2"  # created, never mentioned
    r = store.end(rid, "Set up the pipeline.", work, recorders=[api])
    assert any("bucket-2" in o for o in r.overreach)

    resources2 = {"bucket-1": "v1"}
    api2 = ApiRecorder("cloud", lambda: dict(resources2), kind="resource")
    rid2 = store.begin(work, recorders=[api2])
    resources2["queue-9"] = "v"
    r2 = store.end(rid2, "Created `queue-9`.", work, recorders=[api2])
    assert any("queue-9" in v for v in r2.verified)


def test_non_file_changes_are_sealed_in_the_hash(tmp_path: Path) -> None:
    repo = tmp_path / "r"
    repo.mkdir()
    _repo(repo)
    store = ReceiptStore(tmp_path / ".am")
    rid = store.begin(repo, recorders=[GitRecorder(repo)])
    _git(repo, "branch", "feature/y")
    r = store.end(rid, "made a branch", repo, recorders=[GitRecorder(repo)])
    assert not r.tampered()
    assert r.model_copy(update={"changes": []}).tampered()
