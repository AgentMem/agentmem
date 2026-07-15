"""Is a root-cause answer anchored in the project, or invented out of nothing?"""

from __future__ import annotations

import re
from pathlib import Path

# Tokens that look like code: a path, a dotted/underscored identifier, a call.
# Prose words are ignored; only things a repo could actually contain are checked.
_CODEISH = re.compile(
    r"""
    [A-Za-z0-9_./-]*\.(?:py|yaml|yml|txt|json|toml|cfg|sh|md)   # a file name
    | [A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\(?         # dotted.name
    | [a-z_]{3,}_[a-z_]{3,}                                     # snake_case
    | `[^`]+`                                                   # anything backticked
    """,
    re.X,
)

# Words too generic to prove grounding even when they do appear somewhere.
_STOP = {
    "self.assert",
    "test.py",
    "setup.py",
    "e.g",
    "i.e",
    "etc.py",
}


def candidates(answer: str) -> list[str]:
    """The code-shaped things an answer claims exist."""
    out = []
    for raw in _CODEISH.findall(answer or ""):
        tok = raw.strip("`(").strip()
        if len(tok) < 4 or tok.lower() in _STOP:
            continue
        out.append(tok)
    return sorted(set(out))


def repo_text(repo: Path) -> str:
    """Everything the task's source actually says, lowercased."""
    parts = []
    for p in sorted(repo.rglob("*")):
        if not p.is_file() or ".git" in p.parts:
            continue
        if p.suffix.lower() in {".png", ".jpg", ".gz", ".zip", ".pyc", ".dat"}:
            continue
        parts.append(p.name)
        try:
            parts.append(p.read_text(errors="ignore"))
        except OSError:
            continue
    return "\n".join(parts).lower()


def score(answer: str, repo: Path) -> dict:
    """Split an answer's claims into ones the repo can corroborate and ones it can't.

    Grounded means the answer names at least one real artifact of this project. An
    answer that names none, while confidently asserting a cause, is describing a
    project that does not exist."""
    text = repo_text(repo)
    real, invented = [], []
    for tok in candidates(answer):
        bare = tok.split("/")[-1].split("(")[0].lower()
        (real if bare and bare in text else invented).append(tok)
    return {
        "grounded": bool(real),
        "real": real,
        "invented": invented,
        "n_real": len(real),
        "n_invented": len(invented),
    }
