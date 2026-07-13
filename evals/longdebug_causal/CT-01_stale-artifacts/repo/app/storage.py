"""Loads the demo users from the generated fixtures file."""

import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "users.json"


def load_users() -> list[dict]:
    return json.loads(FIXTURES.read_text())


def get_user(user_id: int) -> dict | None:
    for user in load_users():
        if user["id"] == user_id:
            return user
    return None
