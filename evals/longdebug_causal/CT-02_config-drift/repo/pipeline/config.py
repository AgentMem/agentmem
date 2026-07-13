import tomllib
from pathlib import Path


def cache_enabled() -> bool:
    data = tomllib.loads(Path("config.toml").read_text())
    return bool(data.get("cache", {}).get("enabled", False))
