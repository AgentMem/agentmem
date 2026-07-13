from auth import login


def test_token_lasts_an_hour():
    # A session token should be valid for an hour (3600s), not a minute.
    assert login("alice")["ttl"] == 3600
