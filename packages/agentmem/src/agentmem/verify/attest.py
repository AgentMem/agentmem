"""Sign a receipt so its integrity can be checked offline with only a public key."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import BaseModel

from .ledger import Ledger
from .receipt import ActionReceipt

_ALGO = "ed25519"


def _canonical(obj: dict[str, object]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


class Attestation(BaseModel):
    """An issuer's signature over a receipt's seal, plus the public key to check it."""

    receipt_id: str
    receipt_hash: str
    algo: str
    public_key: str
    signature: str
    signed_at: str

    def message(self) -> bytes:
        return f"{self.algo}:{self.receipt_hash}".encode()


def _public_pem(private_key: Ed25519PrivateKey) -> str:
    return (
        private_key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )


def generate_keypair() -> tuple[str, str]:
    """A fresh Ed25519 (private_pem, public_pem). The private half is the issuer's secret."""
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    return private_pem, _public_pem(private_key)


def sign_receipt(
    receipt: ActionReceipt, private_pem: str, *, signed_at: str | None = None
) -> Attestation:
    """Sign a receipt's seal with an issuer's private key."""
    private_key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("attestation needs an Ed25519 private key")
    public_pem = _public_pem(private_key)
    signature = private_key.sign(f"{_ALGO}:{receipt.hash}".encode()).hex()
    return Attestation(
        receipt_id=receipt.receipt_id,
        receipt_hash=receipt.hash,
        algo=_ALGO,
        public_key=public_pem,
        signature=signature,
        signed_at=signed_at or datetime.now(UTC).isoformat(timespec="seconds"),
    )


def verify_attestation(
    attestation: Attestation,
    receipt: ActionReceipt | None = None,
    *,
    expected_public_key: str | None = None,
) -> bool:
    """Check the signature over the receipt seal with the embedded public key. With a
    receipt, also confirm its facts still hash to the attested seal; with an expected key,
    confirm the signer is who you think, which is what makes the attestation independent."""
    if receipt is not None and (
        receipt.receipt_id != attestation.receipt_id
        or receipt.compute_hash() != attestation.receipt_hash
    ):
        return False
    if (
        expected_public_key is not None
        and attestation.public_key.strip() != expected_public_key.strip()
    ):
        return False
    try:
        public_key = serialization.load_pem_public_key(attestation.public_key.encode())
        if not isinstance(public_key, Ed25519PublicKey):
            return False
        public_key.verify(bytes.fromhex(attestation.signature), attestation.message())
    except Exception:
        return False
    return True


class Certificate(BaseModel):
    """A signed statement about a team's ledger over a period: the counts, whether the chain
    held, and a digest of the receipt seals, so a filing can be verified without the ledger."""

    team: str
    since: str | None
    until: str | None
    total: int
    faithful: int
    flagged: int
    by_verdict: dict[str, int]
    chain_intact: bool
    digest: str
    generated_at: str
    public_key: str
    signature: str

    def payload(self) -> bytes:
        return _canonical(
            {
                "team": self.team,
                "since": self.since,
                "until": self.until,
                "total": self.total,
                "faithful": self.faithful,
                "flagged": self.flagged,
                "by_verdict": self.by_verdict,
                "chain_intact": self.chain_intact,
                "digest": self.digest,
                "generated_at": self.generated_at,
            }
        )


def certify_ledger(
    ledger: Ledger,
    private_pem: str,
    *,
    team: str = "local",
    since: str | None = None,
    until: str | None = None,
    generated_at: str | None = None,
) -> Certificate:
    """Sign a period certificate over a ledger. `digest` is a sha256 of the period's receipt
    seals in order, recomputable by anyone who has the ledger."""
    private_key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("certificate needs an Ed25519 private key")
    records = ledger.records(since=since, until=until)
    digest = hashlib.sha256("\n".join(str(r["receipt_hash"]) for r in records).encode()).hexdigest()
    by_verdict: dict[str, int] = {}
    for record in records:
        outcome = str(record["outcome"])
        by_verdict[outcome] = by_verdict.get(outcome, 0) + 1
    faithful = by_verdict.get("FAITHFUL", 0)
    cert = Certificate(
        team=team,
        since=since,
        until=until,
        total=len(records),
        faithful=faithful,
        flagged=len(records) - faithful,
        by_verdict=by_verdict,
        chain_intact=(ledger.verify() == []),
        digest=digest,
        generated_at=generated_at or datetime.now(UTC).isoformat(timespec="seconds"),
        public_key=_public_pem(private_key),
        signature="",
    )
    cert.signature = private_key.sign(cert.payload()).hex()
    return cert


def verify_certificate(certificate: Certificate, *, expected_public_key: str | None = None) -> bool:
    if (
        expected_public_key is not None
        and certificate.public_key.strip() != expected_public_key.strip()
    ):
        return False
    try:
        public_key = serialization.load_pem_public_key(certificate.public_key.encode())
        if not isinstance(public_key, Ed25519PublicKey):
            return False
        public_key.verify(bytes.fromhex(certificate.signature), certificate.payload())
    except Exception:
        return False
    return True
