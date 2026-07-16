"""Application configuration.

Defaults live here. A deployment can adjust them with a site-local overrides
module that is applied on top, so the values below are not always the last word.
"""

GREETING = "hello"
LANG = "en"
MAX_RETRIES = 3


def describe() -> str:
    return f"greeting={GREETING} lang={LANG} retries={MAX_RETRIES}"


# Site-local overrides are applied last, after the defaults above, so whatever a
# deployment sets in _overrides wins. Keep this import at the bottom.
from _overrides import *  # noqa: E402, F401, F403
