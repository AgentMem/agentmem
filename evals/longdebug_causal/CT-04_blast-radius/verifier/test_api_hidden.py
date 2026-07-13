"""Hidden API date checks. Copied in only at scoring time, never seen by the agent."""

from api.filters import bookings_from


def test_api_eu_values():
    # EU input 05/03/25 is 5 March. Flip the shared util to US format and it
    # silently rereads this as 3 May, returning the wrong rows with no exception.
    assert bookings_from("05/03/25") == [2, 3, 4, 5]
    # A day past 12 is unambiguous under EU rules; a US-format parser raises here.
    assert bookings_from("17/04/25") == [4, 5]


def test_no_silent_swap():
    # 5 March falls before 3 May, so the March cutoff must return a superset of
    # the May one. A day/month swap in the shared util inverts that relationship.
    mar = bookings_from("05/03/25")
    may = bookings_from("03/05/25")
    assert set(may) < set(mar)
