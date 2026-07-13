"""The shared util must stay format-agnostic: callers pass their own format in.
Copied in only at scoring time, never seen by the agent."""

import inspect

from utils.dates import parse_date


def test_util_takes_explicit_format():
    # parse_date must take an explicit format argument instead of hardcoding a
    # region, so the CLI and API can each supply their own boundary format.
    params = list(inspect.signature(parse_date).parameters)
    assert len(params) >= 2, f"parse_date hardcodes a format: {params}"
