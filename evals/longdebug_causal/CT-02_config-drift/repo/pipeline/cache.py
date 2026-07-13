import hashlib
import json
from pathlib import Path

# Bump this when the normalize logic changes so old entries are ignored.
CACHE_SALT = "v1"

_DIR = Path(".cache")


def _key(name: str, payload: object) -> str:
    raw = f"{CACHE_SALT}:{name}:{json.dumps(payload, sort_keys=True)}"
    return hashlib.sha1(raw.encode()).hexdigest()


def cached(name, payload, compute, enabled):
    if not enabled:
        return compute()
    _DIR.mkdir(exist_ok=True)
    slot = _DIR / _key(name, payload)
    if slot.exists():
        return json.loads(slot.read_text())
    result = compute()
    slot.write_text(json.dumps(result))
    return result
