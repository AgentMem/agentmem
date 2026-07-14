"""The FastMCP wrapping around the memory-access core (offline: the SDK isn't installed)."""

from __future__ import annotations

import importlib.util

import pytest
from agentmem import mcp


def _installed(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        return False


@pytest.mark.skipif(_installed("mcp.server.fastmcp"), reason="the MCP SDK is installed")
def test_build_server_points_at_the_extra_when_the_sdk_is_missing() -> None:
    with pytest.raises(ImportError, match=r"agentmem-core\[mcp\]"):
        mcp.build_server()


def test_the_tools_are_backed_by_the_module_functions() -> None:
    assert mcp._CORE["recap"] is mcp.recap
    assert mcp._CORE["search"] is mcp.search
    assert mcp._CORE["bank"] is mcp.bank_text
    assert mcp._CORE["checkpoint"] is mcp.checkpoint
