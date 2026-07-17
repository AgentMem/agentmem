"""Team bearer keys for the hub, loaded from the environment or a file (fail-closed)."""

from __future__ import annotations

import json
import os
from pathlib import Path


def load_keys() -> dict[str, set[str]]:
    """Map of team -> the bearer keys allowed to write and read it.

    From `AGENTMEM_HUB_KEYS` (a JSON object of team -> [keys]) or, if that is unset, from the
    JSON file at `AGENTMEM_HUB_KEYS_FILE`. Missing or malformed config yields no teams, which
    is fail-closed: nothing is accessible until a key is configured.
    """
    raw = os.environ.get("AGENTMEM_HUB_KEYS")
    if not raw:
        path = os.environ.get("AGENTMEM_HUB_KEYS_FILE")
        if path and Path(path).exists():
            raw = Path(path).read_text()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return {str(team): {str(k) for k in keys} for team, keys in data.items()}


def key_ok(keys: dict[str, set[str]], team: str, presented: str) -> bool:
    valid = keys.get(team, set())
    return bool(valid) and presented in valid
