"""Notary timestamps and periodic certificates, both Ed25519-signed and offline-verifiable."""

from __future__ import annotations

from pathlib import Path

from agentmem.cli import main
from agentmem.verify import Ledger, ReceiptStore, Snapshot, verify_run
from agentmem.verify.attest import (
    Certificate,
    certify_ledger,
    generate_keypair,
    sign_receipt,
    verify_certificate,
)
from agentmem.verify.notary import Notary, verify_timestamp


def _receipt(tmp_path: Path, claim: str = "edited `f.py`"):
    root = tmp_path / "work"
    root.mkdir(exist_ok=True)
    (root / "f.py").write_text("1\n")
    before = Snapshot.capture(root)
    (root / "f.py").write_text("2\n")
    after = Snapshot.capture(root)
    return verify_run(before, after, claim)


def test_notary_signs_and_verifies(tmp_path: Path) -> None:
    issuer_private, _ = generate_keypair()
    att = sign_receipt(_receipt(tmp_path), issuer_private)
    notary = Notary(generate_keypair()[0])
    timestamp = notary.notarize(att)
    assert verify_timestamp(timestamp, att)
    assert verify_timestamp(timestamp, att, expected_notary_key=notary.public_key)


def test_notary_verify_fails_on_the_wrong_attestation(tmp_path: Path) -> None:
    issuer_private, _ = generate_keypair()
    att = sign_receipt(_receipt(tmp_path), issuer_private)
    other = sign_receipt(_receipt(tmp_path, "other work"), issuer_private)
    timestamp = Notary(generate_keypair()[0]).notarize(att)
    assert not verify_timestamp(timestamp, other)


def test_notary_log_chains_timestamps(tmp_path: Path) -> None:
    notary = Notary(generate_keypair()[0], log_path=tmp_path / "log.jsonl")
    issuer_private, _ = generate_keypair()
    first = notary.notarize(sign_receipt(_receipt(tmp_path, "a"), issuer_private))
    second = notary.notarize(sign_receipt(_receipt(tmp_path, "b"), issuer_private))
    assert first.seq == 1
    assert second.seq == 2
    assert second.prev_hash  # the second timestamp chains after the first


def test_certificate_signs_and_verifies(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "f.py").write_text("0\n")
    store = ReceiptStore(tmp_path / ".agentmem")
    rid = store.begin(root)
    (root / "f.py").write_text("1\n")
    store.end(rid, "edited `f.py`", root, actor="alice")

    private, public = generate_keypair()
    cert = certify_ledger(Ledger(tmp_path / ".agentmem"), private, team="acme")
    assert cert.total == 1
    assert cert.faithful == 1
    assert cert.chain_intact
    assert verify_certificate(cert)
    assert verify_certificate(cert, expected_public_key=public)
    assert not verify_certificate(cert.model_copy(update={"total": 999}))


def test_cli_attest_certify_and_verify(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "f.py").write_text("0\n")
    main(["audit", "begin", "--repo", str(repo)])
    (repo / "f.py").write_text("1\n")
    main(["audit", "end", "--repo", str(repo), "--claim", "edited `f.py`"])

    private = tmp_path / "k.key"
    public = tmp_path / "k.pub"
    cert = tmp_path / "cert.json"
    main(["attest", "keygen", "--private", str(private), "--public", str(public)])
    assert (
        main(
            [
                "attest",
                "certify",
                "--repo",
                str(repo),
                "--private",
                str(private),
                "--cert",
                str(cert),
            ]
        )
        == 0
    )
    assert main(["attest", "verify-cert", "--cert", str(cert), "--public", str(public)]) == 0

    tampered = Certificate.model_validate_json(cert.read_text()).model_copy(update={"total": 42})
    cert.write_text(tampered.model_dump_json())
    assert main(["attest", "verify-cert", "--cert", str(cert)]) == 1
