# agentmem-hub

The hosted, multi-tenant team feed over AgentMem action receipts. Contributors push their
local receipts; the hub chains them into one tamper-evident team timeline and serves it back
as JSON and as a web feed the whole team can read.

A receipt is already self-verifying, its facts hash to its own seal. The hub adds a second
chain over the sequence it receives, so the team's timeline cannot be silently reordered or
trimmed either. Ingest is idempotent by receipt id and serialized under a lock, so many
machines can push at once. Every team is gated by a bearer key the operator configures; the
web page carries no data and no key in its URL, asking for the key in the browser and
fetching the JSON with it.

## Run it

```bash
pip install agentmem-hub
export AGENTMEM_HUB_KEYS='{"acme": ["a-long-random-key"]}'   # team -> allowed keys
export AGENTMEM_HUB_DATA=/var/lib/agentmem-hub                # where the ledgers live
agentmem-hub                                                  # serves on 127.0.0.1:8791
```

## Push to it

From any project with a local ledger:

```bash
agentmem ledger push --to https://hub.example.com --team acme --key a-long-random-key \
                     --contributor my-laptop
```

## API

| Method & path | What it does |
|---|---|
| `GET /health` | liveness, open |
| `POST /teams/{team}/receipts` | ingest a receipt (bearer key); idempotent by id; 402 over the plan limit |
| `GET /teams/{team}/receipts` | the feed as JSON (bearer key); `?actor=&verdict=&contributor=&limit=` |
| `GET /teams/{team}/verify` | chain integrity (bearer key) |
| `GET /teams/{team}/export` | audit log, JSON or `?format=csv` (bearer key) |
| `GET /teams/{team}/usage` | plan, used, and remaining (bearer key) |
| `GET /teams/{team}` | the web feed (asks for the key in the browser) |
| `POST /billing/webhook` | Stripe webhook; upgrades a team's plan on subscription |
| `POST /notary/timestamp` | countersign an attestation (needs the notary extra + key) |

Keys are supplied by whoever runs the hub, through `AGENTMEM_HUB_KEYS` (JSON) or the file at
`AGENTMEM_HUB_KEYS_FILE`. A team with no configured key can be neither written nor read.

## Deploy

A Dockerfile and a `fly.toml` ship with the package. Build from the repo root:

```bash
docker build -f packages/agentmem-hub/Dockerfile -t agentmem-hub .
# or, on fly.io:
fly deploy --config packages/agentmem-hub/fly.toml
fly secrets set AGENTMEM_HUB_KEYS='{"acme":["a-long-key"]}'
```

## Billing

Each team is on a plan (`free` caps stored receipts, `pro` and `enterprise` are unlimited);
over the cap, ingest returns 402. A Stripe webhook drives upgrades: point Stripe at
`/billing/webhook`, set `AGENTMEM_HUB_WEBHOOK_SECRET`, and map price ids to plans with
`AGENTMEM_HUB_PRICES='{"price_x":"pro"}'`. The signature is checked with stdlib HMAC, no
Stripe SDK.

## Notary

With `pip install agentmem-hub[notary]` and `AGENTMEM_HUB_NOTARY_KEY` set, the hub
countersigns attestations with a timestamp: `POST /notary/timestamp` returns a signature
anyone can check offline against `GET /notary/public`.
