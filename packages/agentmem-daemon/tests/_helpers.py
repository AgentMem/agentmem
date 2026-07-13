"""Shared constants/builders for the daemon tests (uniquely named so it doesn't
collide with the core tests' helper modules on the path)."""

from __future__ import annotations

CWD = "/tmp/proj/demo-app"  # every request in a test uses the same cwd -> same project


def tool_fail_payload(command: str = "pytest -q") -> dict:
    return {
        "cwd": CWD,
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"stdout": "FAILED test_token_expiry"},
    }
