"""Builds the public JSON shape for a user."""


def serialize_user(user: dict) -> dict:
    return {
        "id": user["id"],
        "email": user["email"],
    }
