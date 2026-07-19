"""Billing: plans meter how many receipts a team may store, and a signed Stripe webhook
lifts the cap when a team upgrades."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path

from agentmem.verify import Snapshot, verify_run
from agentmem_hub import plans as plans_mod
from agentmem_hub.app import create_app
from fastapi.testclient import TestClient


def _receipt(tmp_path: Path, i: int):
    root = tmp_path / "work"
    root.mkdir(exist_ok=True)
    (root / "f.py").write_text(f"{i}\n")
    before = Snapshot.capture(root)
    (root / "f.py").write_text(f"{i}-x\n")
    after = Snapshot.capture(root)
    return verify_run(before, after, f"edit {i} `f.py`", actor="alice")


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(base=tmp_path / "hub", keys={"acme": {"k1"}}))


def _push(client: TestClient, receipt):
    return client.post(
        "/teams/acme/receipts",
        json={"receipt": receipt.model_dump(mode="json"), "contributor": "laptop"},
        headers={"Authorization": "Bearer k1"},
    )


def _signature(payload: bytes, secret: str) -> str:
    timestamp = str(int(time.time()))
    v1 = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={v1}"


def test_free_plan_caps_receipts(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setitem(plans_mod.PLANS["free"], "max_receipts", 1)
    client = _client(tmp_path)
    assert _push(client, _receipt(tmp_path, 1)).status_code == 200
    assert _push(client, _receipt(tmp_path, 2)).status_code == 402


def test_usage_reports_plan_and_limit(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setitem(plans_mod.PLANS["free"], "max_receipts", 5)
    client = _client(tmp_path)
    _push(client, _receipt(tmp_path, 1))
    usage = client.get("/teams/acme/usage", headers={"Authorization": "Bearer k1"}).json()
    assert usage["plan"] == "free"
    assert usage["used"] == 1
    assert usage["limit"] == 5
    assert usage["remaining"] == 4


def test_webhook_upgrade_lifts_the_cap(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setitem(plans_mod.PLANS["free"], "max_receipts", 1)
    monkeypatch.setenv("AGENTMEM_HUB_WEBHOOK_SECRET", "whsec_test")
    client = _client(tmp_path)
    assert _push(client, _receipt(tmp_path, 1)).status_code == 200
    assert _push(client, _receipt(tmp_path, 2)).status_code == 402  # capped on free

    event = json.dumps(
        {
            "type": "customer.subscription.created",
            "data": {"object": {"metadata": {"team": "acme", "plan": "pro"}, "status": "active"}},
        }
    ).encode()
    resp = client.post(
        "/billing/webhook",
        content=event,
        headers={"stripe-signature": _signature(event, "whsec_test")},
    )
    assert resp.json()["plan"] == "pro"
    assert _push(client, _receipt(tmp_path, 3)).status_code == 200  # cap lifted


def test_webhook_rejects_a_bad_signature(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("AGENTMEM_HUB_WEBHOOK_SECRET", "whsec_test")
    client = _client(tmp_path)
    event = json.dumps({"type": "customer.subscription.created", "data": {"object": {}}}).encode()
    resp = client.post(
        "/billing/webhook", content=event, headers={"stripe-signature": "t=1,v1=deadbeef"}
    )
    assert resp.status_code == 400
