# Requirements

## Date formats
- The **CLI** accepts US dates: `mm/dd/yy`.
- The **API** accepts EU dates: `dd/mm/yy`.

## Shared code
Anything under `utils/` is imported by both the CLI and the API, so it MUST stay
format-agnostic. Format handling belongs at each boundary: the CLI passes the US
format, the API passes the EU format. Never bake a regional format into `utils/`.

## Tests
Everything must pass with `python -m pytest`, and both the CLI and the API date
paths stay covered.
