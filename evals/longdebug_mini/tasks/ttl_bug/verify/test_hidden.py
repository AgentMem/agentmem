"""Hidden verifier: the ground truth for pass@1. Copied into the workdir as _verify/
only at scoring time, so the agent never sees it."""

import inspect

from api import make_token
from auth import login


def test_token_lasts_an_hour():
    assert login("alice")["ttl"] == 3600


def test_public_api_unchanged():
    # The whole point of the constraint: make_token stays a one-argument function.
    params = list(inspect.signature(make_token).parameters)
    assert params == ["user"], f"make_token signature changed to {params}"
