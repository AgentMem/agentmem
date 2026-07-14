"""Enables `python -m agentmem`, which the command hooks use to spawn a detached step."""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
