"""Ed25519 attestation over receipts, and the audit-log export."""

from __future__ import annotations

import json
from pathlib import Path

from agentmem.cli import main
from agentmem.verify import Ledger, ReceiptStore, Snapshot, verify_run
from agentmem.verify.attest import Attestation, generate_keypair, sign_receipt, verify_attestation


def _receipt(tmp_path: Path, claim: str = "edited `f.py`", actor: str = "alice"):
    root = tmp_path / "work"
    root.mkdir(exist_ok=True)
    (root / "f.py").write_text("1\n")
    before = Snapshot.capture(root)
    (root / "f.py").write_text("2\n")
    after = Snapshot.capture(root)
    return verify_run(before, after, claim, actor=actor)


def test_sign_and_verify_round_trip(tmp_path: Path) -> None:
    private_pem, public_pem = generate_keypair()
    receipt = _receipt(tmp_path)
    att = sign_receipt(receipt, private_pem)
    assert verify_attestation(att, receipt)
    assert verify_attestation(att, receipt, expected_public_key=public_pem)


def test_verify_fails_on_tampered_receipt(tmp_path: Path) -> None:
    private_pem, _ = generate_keypair()
    receipt = _receipt(tmp_path)
    att = sign_receipt(receipt, private_pem)
    assert not verify_attestation(att, receipt.model_copy(update={"claim": "something else"}))


def test_verify_fails_on_the_wrong_expected_key(tmp_path: Path) -> None:
    private_pem, _ = generate_keypair()
    _, other_public = generate_keypair()
    receipt = _receipt(tmp_path)
    att = sign_receipt(receipt, private_pem)
    assert not verify_attestation(att, receipt, expected_public_key=other_public)


def test_verify_fails_on_a_forged_signature(tmp_path: Path) -> None:
    private_pem, _ = generate_keypair()
    receipt = _receipt(tmp_path)
    att = sign_receipt(receipt, private_pem).model_copy(update={"signature": "00" * 64})
    assert not verify_attestation(att, receipt)


def test_cli_attest_keygen_sign_verify(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "f.py").write_text("0\n")
    main(["audit", "begin", "--repo", str(repo)])
    (repo / "f.py").write_text("1\n")
    main(["audit", "end", "--repo", str(repo), "--claim", "edited `f.py`"])

    private = tmp_path / "k.key"
    public = tmp_path / "k.pub"
    att = tmp_path / "a.json"
    assert main(["attest", "keygen", "--private", str(private), "--public", str(public)]) == 0
    assert private.exists() and public.exists()
    assert (
        main(["attest", "sign", "--repo", str(repo), "--private", str(private), "--att", str(att)])
        == 0
    )
    assert (
        main(["attest", "verify", "--repo", str(repo), "--att", str(att), "--public", str(public)])
        == 0
    )

    forged = Attestation.model_validate_json(att.read_text()).model_copy(
        update={"signature": "00" * 64}
    )
    att.write_text(forged.model_dump_json())
    assert main(["attest", "verify", "--repo", str(repo), "--att", str(att)]) == 1


def test_ledger_export_json_and_csv(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "f.py").write_text("0\n")
    store = ReceiptStore(tmp_path / ".agentmem")
    rid = store.begin(root)
    (root / "f.py").write_text("1\n")
    store.end(rid, "edited `f.py`", root, actor="alice")

    ledger = Ledger(tmp_path / ".agentmem")
    data = json.loads(ledger.export(fmt="json"))
    assert data["format"] == "agentmem-audit-log/1"
    assert len(data["records"]) == 1
    record = data["records"][0]
    assert record["actor"] == "alice"
    assert record["outcome"] == "FAITHFUL"
    assert record["receipt_hash"]

    csv_text = ledger.export(fmt="csv")
    assert csv_text.splitlines()[0].startswith("timestamp,actor,action")
    assert "alice" in csv_text
