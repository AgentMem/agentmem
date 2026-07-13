import tomllib
from pathlib import Path


def timeout_s() -> float:
    return float(tomllib.loads(Path("worker/config.toml").read_text())["timeout_s"])
