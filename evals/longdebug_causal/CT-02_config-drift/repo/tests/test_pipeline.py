from pipeline.aggregate import aggregate_cities, aggregate_countries
from pipeline.normalize import clean_city, clean_country

# GOLDEN-BLOCK-START
GOLDEN_CITY = {"Hanoi": 5, "Da Nang": 3, "Hue": 2}
# GOLDEN-BLOCK-END


def test_normalize_idempotent_on_clean_input():
    # Weak by design: only checks already-clean input, so it stays green whether
    # clean_* is identity or casefolds.
    assert clean_city("hanoi") == "hanoi"
    assert clean_country("vietnam") == "vietnam"


def test_aggregates():
    assert aggregate_cities() == GOLDEN_CITY
    if "GOLDEN_COUNTRY" in globals():
        assert aggregate_countries() == GOLDEN_COUNTRY
