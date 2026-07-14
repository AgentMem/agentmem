"""Daemon test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest
from agentmem import MemorySession
from agentmem._demo import ScriptedProvider
from agentmem.config import AgentMemConfig
from agentmem_daemon import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path):
    def factory(key: str, cwd: str, task: str) -> MemorySession:
        config = AgentMemConfig(state_dir=str(tmp_path / key), max_tool_rounds=1)
        return MemorySession(
            task=task,
            session_id=key,
            config=config,
            provider=ScriptedProvider(),
            async_worker=False,
        )

    app = create_app(factory=factory)
    with TestClient(app) as c:
        yield c
