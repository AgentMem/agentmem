# server/ (planned)

The hosted API — a thin FastAPI service that reuses the `agentmem` core and adds
multi-tenancy, auth, and metering. This is the SaaS tier, and it only gets built
after the OSS core has traction.

Sketch: `POST /v1/sessions`, `POST /v1/sessions/{id}/events`, `GET .../context`,
Postgres for banks and usage, API-key auth. Everything the OSS version does stays
local-first and free; hosting is opt-in.

Nothing here yet.
