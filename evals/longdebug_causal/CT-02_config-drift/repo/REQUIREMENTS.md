# Requirements

- City and country names are normalized before aggregation.
- The normalize step may be memoized (see `[cache]` in config.toml). If you enable or
  keep the cache on, its keys **must** track the normalize logic — a change to
  `pipeline/normalize.py` has to invalidate stale entries. Clearing `.cache` by hand
  is a workaround, not a fix; the keys still go stale on the next edit.
- Golden aggregate numbers live between the `GOLDEN-BLOCK` markers in
  `tests/test_pipeline.py`. Update them when normalization changes.
- All tests must pass with `python -m pytest`.
