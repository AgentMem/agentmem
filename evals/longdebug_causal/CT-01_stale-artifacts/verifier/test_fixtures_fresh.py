"""Derived artifacts must match what codegen would produce from the current
schema. Catches stale files left behind when make generate wasn't run."""

from pathlib import Path

import tools.codegen as codegen

ROOT = Path(codegen.__file__).resolve().parent.parent


def test_fixtures_fresh():
    fields = codegen.load_schema()
    on_disk = (ROOT / "tests" / "fixtures" / "users.json").read_text()
    assert on_disk == codegen.fixtures_json(fields)


def test_models_fresh():
    fields = codegen.load_schema()
    on_disk = (ROOT / "generated" / "models.py").read_text()
    assert on_disk == codegen.models_source(fields)
