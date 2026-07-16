from config import GREETING


def test_greeting_is_welcome():
    # The product copy was signed off as "welcome". Whatever config resolves to at
    # import time has to match it.
    assert GREETING == "welcome", f"greeting resolved to {GREETING!r}, expected 'welcome'"
