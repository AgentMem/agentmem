"""Tiny in-memory user API."""

from app.serializer import serialize_user
from app.storage import get_user, load_users


def list_users(limit: int | None = None, offset: int = 0) -> list[dict]:
    users = load_users()[offset:]
    if limit is not None:
        users = users[:limit]
    return [serialize_user(u) for u in users]


def read_user(user_id: int) -> dict | None:
    user = get_user(user_id)
    if user is None:
        return None
    return serialize_user(user)
