"""Verify an agent's account of its work against ground truth.

The agent is an untrusted witness. `verify_account` checks what an agent said it did
against a repository checkout and returns a flight-recorder `AccountReport`.
"""

from .grounding import candidates, score
from .report import AccountReport, verify_account

__all__ = ["AccountReport", "candidates", "score", "verify_account"]
