"""Store round-trip tests for both backends."""

from __future__ import annotations

from pathlib import Path

import pytest
from agentmem.schemas import MemoryBank, MemoryEntry
from agentmem.store import JsonFileStore, SqliteStore, open_store


def _sample_bank() -> MemoryBank:
    bank = MemoryBank(status="halfway", seq_knowledge=1, version=3)
    bank.knowledge["K-001"] = MemoryEntry(
        id="K-001", kind="knowledge", tag="env", content="py3.11", created_step=1, updated_step=1
    )
    return bank


@pytest.fixture(params=["json", "sqlite"])
def store(request: pytest.FixtureRequest, tmp_path: Path):
    if request.param == "json":
        s = JsonFileStore(str(tmp_path))
    else:
        s = SqliteStore(str(tmp_path / "t.db"))
    yield s
    s.close()


def test_round_trip(store) -> None:  # noqa: ANN001
    bank = _sample_bank()
    store.save_bank("sess", "my task", bank)
    loaded = store.load_bank("sess")
    assert loaded == bank  # includes status, version, and the id counter


def test_missing_session_is_none(store) -> None:  # noqa: ANN001
    assert store.load_bank("never-saved") is None


def test_list_sessions(store) -> None:  # noqa: ANN001
    store.save_bank("a", "task a", MemoryBank())
    store.save_bank("b", "task b", MemoryBank())
    ids = {s.session_id for s in store.list_sessions()}
    assert ids == {"a", "b"}


def test_save_overwrites(store) -> None:  # noqa: ANN001
    store.save_bank("s", "t", MemoryBank(version=1))
    store.save_bank("s", "t", MemoryBank(version=2))
    assert store.load_bank("s").version == 2
    assert len(store.list_sessions()) == 1


def test_open_store_dispatch(tmp_path: Path) -> None:
    assert isinstance(open_store("json", str(tmp_path)), JsonFileStore)
    assert isinstance(open_store("sqlite", str(tmp_path)), SqliteStore)
    assert isinstance(open_store(f"sqlite:///{tmp_path}/run.db"), SqliteStore)
    with pytest.raises(ValueError):
        open_store("mongodb://nope")
