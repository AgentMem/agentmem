"""The hosted team feed: auth, idempotent ingest, tamper rejection, the multi-contributor chain, and push."""

from __future__ import annotations

from pathlib import Path

from agentmem.verify import Snapshot, verify_run
from agentmem.verify.receipt import ActionReceipt
from agentmem_hub.app import create_app
from fastapi.testclient import TestClient


def _receipt(tmp_path: Path, claim: str = "edited `f.py`", actor: str = "alice") -> ActionReceipt:
    root = tmp_path / "work"
    root.mkdir(exist_ok=True)
    (root / "f.py").write_text("1\n")
    before = Snapshot.capture(root)
    (root / "f.py").write_text("2\n")
    after = Snapshot.capture(root)
    return verify_run(before, after, claim, actor=actor)


def _client(tmp_path: Path) -> TestClient:
    app = create_app(base=tmp_path / "hub", keys={"acme": {"k1"}})
    return TestClient(app)


def _push(client: TestClient, receipt: ActionReceipt, contributor: str, key: str = "k1"):
    return client.post(
        "/teams/acme/receipts",
        json={"receipt": receipt.model_dump(mode="json"), "contributor": contributor},
        headers={"Authorization": f"Bearer {key}"},
    )


def test_health_is_open(tmp_path: Path) -> None:
    assert _client(tmp_path).get("/health").json()["ok"] is True


def test_ingest_requires_a_valid_key(tmp_path: Path) -> None:
    client = _client(tmp_path)
    r = _receipt(tmp_path)
    body = {"receipt": r.model_dump(mode="json"), "contributor": "alice"}
    assert client.post("/teams/acme/receipts", json=body).status_code == 401
    assert (
        client.post(
            "/teams/acme/receipts", json=body, headers={"Authorization": "Bearer wrong"}
        ).status_code
        == 401
    )
    assert _push(client, r, "alice").status_code == 200


def test_ingest_is_idempotent(tmp_path: Path) -> None:
    client = _client(tmp_path)
    r = _receipt(tmp_path)
    assert _push(client, r, "alice").json()["stored"] is True
    assert _push(client, r, "alice").json()["stored"] is False  # same id, not stored twice


def test_ingest_rejects_a_tampered_receipt(tmp_path: Path) -> None:
    client = _client(tmp_path)
    r = _receipt(tmp_path)
    tampered = r.model_copy(update={"claim": "I did something else entirely"})
    assert _push(client, tampered, "alice").status_code == 422


def test_feed_lists_and_filters(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _push(client, _receipt(tmp_path, "alice edited `f.py`", "alice"), "alice-laptop")
    _push(client, _receipt(tmp_path, "bob edited `f.py` and added `ghost.py`", "bot"), "ci-runner")

    feed = client.get("/teams/acme/receipts", headers={"Authorization": "Bearer k1"}).json()
    assert feed["summary"]["total"] == 2
    assert set(feed["summary"]["contributors"]) == {"alice-laptop", "ci-runner"}
    assert feed["entries"][0]["verdict"]  # each entry carries a computed verdict

    flagged = client.get(
        "/teams/acme/receipts?verdict=FABRICATED", headers={"Authorization": "Bearer k1"}
    ).json()
    assert len(flagged["entries"]) == 1
    assert flagged["entries"][0]["actor"] == "bot"


def test_chain_is_intact_across_contributors(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _push(client, _receipt(tmp_path, "alice edited `f.py`", "alice"), "alice-laptop")
    _push(client, _receipt(tmp_path, "bob edited `f.py`", "bob"), "bob-laptop")
    verify = client.get("/teams/acme/verify", headers={"Authorization": "Bearer k1"}).json()
    assert verify["intact"] is True
    assert verify["problems"] == []


def test_feed_page_is_a_shell_with_no_data_or_key(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _push(client, _receipt(tmp_path, "secret work on `f.py`"), "alice")
    page = client.get("/teams/acme").text
    assert "What acme actually did" in page
    assert "team key" in page  # the page prompts for the key in the browser
    assert "secret work" not in page  # no receipt data is embedded server-side
    assert "k1" not in page  # and no key


def test_cli_push_round_trip(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    # `agentmem ledger push` sends a local ledger to the hub, and it shows up in the feed.
    import urllib.request

    from agentmem.cli import main

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "f.py").write_text("0\n")
    main(["audit", "begin", "--repo", str(repo)])
    (repo / "f.py").write_text("1\n")
    main(["audit", "end", "--repo", str(repo), "--claim", "edited `f.py`", "--actor", "alice"])

    client = _client(tmp_path)

    class _Resp:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def read(self) -> bytes:
            return self._data

        def __enter__(self) -> _Resp:
            return self

        def __exit__(self, *_a: object) -> bool:
            return False

    def fake_urlopen(request, timeout=None):  # noqa: ANN001, ANN202
        path = "/" + request.full_url.split("://", 1)[-1].split("/", 1)[1]
        response = client.post(path, content=request.data, headers=dict(request.headers))
        return _Resp(response.content)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    code = main(
        [
            "ledger",
            "push",
            "--repo",
            str(repo),
            "--to",
            "http://hub.test",
            "--team",
            "acme",
            "--key",
            "k1",
            "--contributor",
            "laptop",
        ]
    )
    assert code == 0
    feed = client.get("/teams/acme/receipts", headers={"Authorization": "Bearer k1"}).json()
    assert feed["summary"]["total"] == 1
    assert feed["entries"][0]["actor"] == "alice"
    assert feed["entries"][0]["contributor"] == "laptop"


def test_export_endpoint(tmp_path: Path) -> None:
    client = _client(tmp_path)
    _push(client, _receipt(tmp_path, "alice edited `f.py`", "alice"), "alice-laptop")

    data = client.get("/teams/acme/export", headers={"Authorization": "Bearer k1"}).json()
    assert data["format"] == "agentmem-audit-log/1"
    assert len(data["records"]) == 1
    assert data["records"][0]["contributor"] == "alice-laptop"

    csv = client.get("/teams/acme/export?format=csv", headers={"Authorization": "Bearer k1"})
    assert csv.headers["content-type"].startswith("text/csv")
    assert "alice" in csv.text

    assert client.get("/teams/acme/export").status_code == 401
