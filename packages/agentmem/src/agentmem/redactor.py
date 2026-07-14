"""Scrub obvious secrets out of the trajectory before the LLM or telemetry sees it."""

from __future__ import annotations

import re
from collections.abc import Callable

_PLACEHOLDER = "[redacted:{label}]"

# (label, pattern). Specific, high-confidence shapes first so their labels win over
# the generic key=value catch-all.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "private-key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL
        ),
    ),
    ("anthropic-key", re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}")),
    ("openai-key", re.compile(r"sk-[A-Za-z0-9]{20,}")),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("slack-token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("bearer", re.compile(r"(?i)\b(authorization\s*:\s*bearer\s+)[A-Za-z0-9._~+/=-]{8,}")),
    # Generic "SECRET=value" / "api_key: value", only when the name signals a secret
    # so we don't mask every assignment in the file.
    (
        "secret-assignment",
        re.compile(
            r"(?i)\b([A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PASSWD|API[_-]?KEY|ACCESS[_-]?KEY)[A-Z0-9_]*\s*[:=]\s*)"
            r"['\"]?([A-Za-z0-9._~+/=-]{6,})['\"]?"
        ),
    ),
]


def _mask_value(label: str) -> Callable[[re.Match[str]], str]:
    # Keep the name/prefix (group 1), mask only the value, so the line stays
    # readable: "Authorization: Bearer [redacted:bearer]".
    def repl(m: re.Match[str]) -> str:
        return m.group(1) + _PLACEHOLDER.format(label=label)

    return repl


def redact(text: str) -> str:
    """Replace recognized secrets with a labeled placeholder."""
    for label, pattern in _PATTERNS:
        if label in ("bearer", "secret-assignment"):
            text = pattern.sub(_mask_value(label), text)
        else:
            text = pattern.sub(_PLACEHOLDER.format(label=label), text)
    return text


def make_redactor(enabled: bool) -> Callable[[str], str] | None:
    """The redactor when enabled, or None to skip the pass entirely."""
    return redact if enabled else None
