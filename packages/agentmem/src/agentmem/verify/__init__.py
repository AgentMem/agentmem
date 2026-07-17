"""Verify an agent's account of its work against ground truth: the repo, or the real diff of
a span."""

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
