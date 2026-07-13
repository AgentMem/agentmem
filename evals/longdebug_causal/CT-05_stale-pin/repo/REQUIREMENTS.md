# Requirements

- httpx is pinned in more than one place. If you change the pin, update every place it
  appears (requirements.txt and constraints.txt) plus the code that depends on the
  version's API.
- CI installs with constraints.txt; local setup does not. Keep them consistent.
- `bash scripts/setup.sh && .venv/bin/python -m pytest -q` must pass.
