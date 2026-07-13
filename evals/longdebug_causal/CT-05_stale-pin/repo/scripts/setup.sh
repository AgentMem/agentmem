#!/usr/bin/env bash
# Local dev setup: install from requirements only.
set -e
python3 -m venv .venv
.venv/bin/pip install --quiet --disable-pip-version-check -r requirements.txt pytest
