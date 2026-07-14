"""Tests for the secret redactor."""

from __future__ import annotations

from agentmem.redactor import make_redactor, redact


def test_masks_anthropic_key() -> None:
    out = redact("export ANTHROPIC_API_KEY=sk-ant-api03-abcdefghijklmnop1234")
    assert "sk-ant-" not in out
    assert "[redacted:" in out


def test_masks_bearer_but_keeps_header_name() -> None:
    out = redact("Authorization: Bearer abcdef1234567890xyz")
    assert out.startswith("Authorization: Bearer ")
    assert "abcdef1234567890xyz" not in out


def test_masks_generic_secret_assignment() -> None:
    out = redact('DATABASE_PASSWORD = "sup3r-s3cret-value"')
    assert "sup3r-s3cret-value" not in out
    assert "DATABASE_PASSWORD" in out  # the name stays, only the value goes


def test_masks_private_key_block() -> None:
    blob = "-----BEGIN RSA PRIVATE KEY-----\nMIIabc123\n-----END RSA PRIVATE KEY-----"
    assert "MIIabc123" not in redact(blob)


def test_leaves_ordinary_code_alone() -> None:
    code = "def add(a, b):\n    return a + b  # count = 42"
    assert redact(code) == code


def test_make_redactor_toggle() -> None:
    assert make_redactor(True) is redact
    assert make_redactor(False) is None
