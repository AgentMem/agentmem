#!/usr/bin/env bash
# CI-style clean install: honors constraints.txt, the way a locked runner would.
set -e
W="$1"
cd "$W"
rm -rf .venv-ci
python3 -m venv .venv-ci
.venv-ci/bin/pip install --quiet --disable-pip-version-check -r requirements.txt -c constraints.txt pytest
PYTHONPATH="$W" .venv-ci/bin/python -m pytest -q
