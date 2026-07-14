"""Pure helpers of the live causal runner."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "causal_run_live", Path(__file__).resolve().parents[1] / "longdebug_causal" / "run_live.py"
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["causal_run_live"] = _mod
_spec.loader.exec_module(_mod)


def test_localize_rewrites_uv_invocations() -> None:
    assert _mod._localize("uv run pytest tests/x.py -q") == "python -m pytest tests/x.py -q"
    assert _mod._localize("uv run scripts/tool.py") == "python scripts/tool.py"
    assert _mod._localize("plain pytest stays") == "plain pytest stays"


def test_sessions_load_with_localized_commands() -> None:
    sessions = _mod.load_sessions(_mod.HERE / _mod.SM.task_dir("CT-01"))
    assert len(sessions) == 5
    assert all("uv run" not in s["visible"] and "uv run" not in s["ticket"] for s in sessions)
