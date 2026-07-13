"""Public API. Other services depend on these signatures — don't change them."""

from config import DEFAULT_TTL


def make_token(user):
    return {"user": user, "ttl": DEFAULT_TTL}
