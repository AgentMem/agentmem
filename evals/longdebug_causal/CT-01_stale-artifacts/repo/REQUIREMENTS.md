# Requirements

- `generated/` and `tests/fixtures/` are DERIVED from `schema/*.yaml`.
  Never edit them by hand.
- Run `make generate` after ANY change to the schema.
- All tests must pass with `uv run pytest`.
