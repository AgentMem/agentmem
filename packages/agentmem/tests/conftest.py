"""Pytest fixtures. The reusable test doubles live in _fakes.py so they can be
imported directly; this file just wires the common ones up as fixtures."""

from __future__ import annotations

import pytest
from _fakes import FakeProvider


@pytest.fixture
def fake_provider() -> FakeProvider:
    return FakeProvider()
