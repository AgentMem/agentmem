"""Run the hub: `agentmem-hub` (or `python -m agentmem_hub`). Configure teams and keys with
AGENTMEM_HUB_KEYS (JSON of team -> [keys]) and the data dir with AGENTMEM_HUB_DATA."""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    from .app import create_app

    host = os.environ.get("AGENTMEM_HUB_HOST", "127.0.0.1")
    port = int(os.environ.get("AGENTMEM_HUB_PORT", "8791"))
    print(f"AgentMem hub on http://{host}:{port}  (Ctrl-C to stop)")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
