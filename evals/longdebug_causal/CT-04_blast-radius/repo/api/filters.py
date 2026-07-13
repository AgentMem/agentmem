"""Booking filters for the web API. Query dates arrive the EU way: dd/mm/yy."""

from datetime import date

from utils.dates import parse_date

# A tiny demo table, ordered by id, with resolved booking dates.
BOOKINGS = [
    {"id": 1, "on": date(2025, 2, 10)},
    {"id": 2, "on": date(2025, 3, 5)},
    {"id": 3, "on": date(2025, 3, 20)},
    {"id": 4, "on": date(2025, 5, 3)},
    {"id": 5, "on": date(2025, 6, 1)},
]


def bookings_from(raw):
    """Ids of bookings on or after an EU-format cutoff date."""
    cutoff = parse_date(raw)
    return [b["id"] for b in BOOKINGS if b["on"] >= cutoff]
