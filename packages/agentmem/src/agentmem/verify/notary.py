"""A notary countersigns an attestation with a timestamp, chained so its order is provable;
a third party runs it and the signature verifies offline with the notary's public key."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import BaseModel

from .attest import Attestation


def _attestation_hash(attestation: Attestation) -> str:
    return hashlib.sha256(
        f"{attestation.receipt_hash}:{attestation.signature}".encode()
    ).hexdigest()


class Timestamp(BaseModel):
    """A notary's signed statement that it saw an attestation at a time and chain position."""

    attestation_hash: str
    notary_public_key: str
    seq: int
    prev_hash: str
    timestamped_at: str
    signature: str

    def message(self) -> bytes:
        return json.dumps(
            {
                "attestation_hash": self.attestation_hash,
                "seq": self.seq,
                "prev_hash": self.prev_hash,
                "timestamped_at": self.timestamped_at,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()


class Notary:
    """Holds the notary's key and, optionally, a chained log so its timestamps are ordered."""

    def __init__(self, private_pem: str, log_path: Path | str | None = None) -> None:
        key = serialization.load_pem_private_key(private_pem.encode(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("notary needs an Ed25519 private key")
        self._key = key
        self.public_key = (
            key.public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode()
        )
        self.log_path = Path(log_path) if log_path else None

    def _head(self) -> tuple[int, str]:
        if not self.log_path or not self.log_path.exists():
            return (0, "")
        lines = [ln for ln in self.log_path.read_text().splitlines() if ln.strip()]
        if not lines:
            return (0, "")
        last = json.loads(lines[-1])
        return (int(last["seq"]), str(last["hash"]))

    def notarize(self, attestation: Attestation, *, timestamped_at: str | None = None) -> Timestamp:
        prev_seq, prev_hash = self._head()
        timestamp = Timestamp(
            attestation_hash=_attestation_hash(attestation),
            notary_public_key=self.public_key,
            seq=prev_seq + 1,
            prev_hash=prev_hash,
            timestamped_at=timestamped_at or datetime.now(UTC).isoformat(timespec="seconds"),
            signature="",
        )
        timestamp.signature = self._key.sign(timestamp.message()).hex()
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            entry_hash = hashlib.sha256(
                timestamp.message() + timestamp.signature.encode()
            ).hexdigest()
            with self.log_path.open("a") as handle:
                handle.write(json.dumps({"seq": timestamp.seq, "hash": entry_hash}) + "\n")
        return timestamp


def verify_timestamp(
    timestamp: Timestamp,
    attestation: Attestation | None = None,
    *,
    expected_notary_key: str | None = None,
) -> bool:
    """Check the notary's signature, and that it timestamps this attestation and this notary."""
    if attestation is not None and _attestation_hash(attestation) != timestamp.attestation_hash:
        return False
    if (
        expected_notary_key is not None
        and timestamp.notary_public_key.strip() != expected_notary_key.strip()
    ):
        return False
    try:
        public_key = serialization.load_pem_public_key(timestamp.notary_public_key.encode())
        if not isinstance(public_key, Ed25519PublicKey):
            return False
        public_key.verify(bytes.fromhex(timestamp.signature), timestamp.message())
    except Exception:
        return False
    return True
