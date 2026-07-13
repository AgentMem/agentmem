from pipeline.aggregate import aggregate_cities, aggregate_countries


def test_city_counts_fresh():
    assert aggregate_cities() == {"hanoi": 5, "da nang": 3, "hue": 2}


def test_country_counts_fresh():
    assert aggregate_countries() == {"vietnam": 10}
