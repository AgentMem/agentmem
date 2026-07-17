"""Sign a receipt so its integrity can be checked offline with only a public key."""

from __future__ import annotations

from datetime import UTC, datetime

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import BaseModel

from .receipt import ActionReceipt

_ALGO = "ed25519"


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
