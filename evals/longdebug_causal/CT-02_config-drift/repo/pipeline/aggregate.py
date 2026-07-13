from collections import Counter

from pipeline.cache import cached
from pipeline.config import cache_enabled
from pipeline.data import RECORDS
from pipeline.normalize import normalize


def _normalized():
    # The normalize step is the cached one, the cache key must track its logic.
    return cached("normalize", RECORDS, lambda: normalize(RECORDS), cache_enabled())


def aggregate_cities():
    return dict(Counter(r["city"] for r in _normalized()))


def aggregate_countries():
    return dict(Counter(r["country"] for r in _normalized()))
