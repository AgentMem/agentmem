"""Checks the API serializer exposes the schema-driven fields with the right
values for every demo user. Imports the repo directly off PYTHONPATH."""

import tools.codegen as codegen
from app.serializer import serialize_user
from app.storage import load_users

# Ground truth for the demo accounts, independent of what's on disk.
EXPECTED = {
    1: {"display_name": "Ada Lovelace", "pronouns": ""},
    2: {"display_name": "Alan Turing", "pronouns": ""},
    3: {"display_name": "Grace Hopper", "pronouns": ""},
}


def _schema_fields() -> set[str]:
    return {f["name"] for f in codegen.load_schema()}


def test_display_name_present():
    for user in load_users():
        assert "display_name" in serialize_user(user)


def test_display_name_value():
    for user in load_users():
        out = serialize_user(user)
        assert out.get("display_name") == EXPECTED[user["id"]]["display_name"]


def test_pronouns_value():
    if "pronouns" not in _schema_fields():
        return
    for user in load_users():
        out = serialize_user(user)
        assert out.get("pronouns") == EXPECTED[user["id"]]["pronouns"]
