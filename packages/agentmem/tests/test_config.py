"""A project can pin settings in a committable agentmem.toml; env and kwargs still win."""

from __future__ import annotations

from pathlib import Path

import pytest
from agentmem.config import AgentMemConfig


def test_agentmem_toml_is_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "agentmem.toml").write_text('model = "claude-sonnet-5"\nmax_bullets = 2\n')
    monkeypatch.chdir(tmp_path)
    config = AgentMemConfig()
    assert config.model == "claude-sonnet-5"
    assert config.max_bullets == 2


def test_env_overrides_the_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "agentmem.toml").write_text('model = "claude-sonnet-5"\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENTMEM_MODEL", "claude-opus-4-8")
    assert AgentMemConfig().model == "claude-opus-4-8"


def test_constructor_overrides_the_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "agentmem.toml").write_text('model = "claude-sonnet-5"\n')
    monkeypatch.chdir(tmp_path)
    assert AgentMemConfig(model="claude-haiku-4-5").model == "claude-haiku-4-5"


def test_no_toml_falls_back_to_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # no agentmem.toml here
    assert AgentMemConfig().model == "claude-haiku-4-5"
