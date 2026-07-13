"""Adapters that wire AgentMem into specific agent harnesses.

Everything here depends on the public `agentmem` API and nothing in the core ever
imports back from this package. Each adapter's job is the same: translate a harness's
events into `mem.observe(...)` and hand `mem.pending_context()` back as context,
without touching the action agent itself.
"""

from __future__ import annotations
