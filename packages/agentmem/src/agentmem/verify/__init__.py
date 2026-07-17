"""Verify an agent's account of its work against ground truth.

The agent is an untrusted witness. `verify_account` checks what an agent said it did
against a repository checkout (a flight-recorder `AccountReport`). `verify_run` and the
`ReceiptStore` go further: they capture the real before and after around a span of work,
so the account can be checked against what measurably changed, and undone.
"""

from .grounding import candidates, path_candidates, score
from .ledger import Ledger
from .receipt import (
    ActionReceipt,
    Check,
    Effect,
    ReceiptStore,
    Snapshot,
    UndoResult,
    build_receipt,
    undo,
    verify_run,
)
from .recorders import ApiRecorder, Change, GitRecorder, Recorder
from .report import AccountReport, verify_account

__all__ = [
    "AccountReport",
    "ActionReceipt",
    "ApiRecorder",
    "Change",
    "Check",
    "Effect",
    "GitRecorder",
    "Ledger",
    "ReceiptStore",
    "Recorder",
    "Snapshot",
    "UndoResult",
    "build_receipt",
    "candidates",
    "path_candidates",
    "score",
    "undo",
    "verify_account",
    "verify_run",
]
