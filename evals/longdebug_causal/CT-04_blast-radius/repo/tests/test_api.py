from api.filters import bookings_from


def test_bookings_from_eu():
    # An EU date like 05/03/25 means 5 March 2025.
    assert bookings_from("05/03/25") == [2, 3, 4, 5]
