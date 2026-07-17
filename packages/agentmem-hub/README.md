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
| `POST /teams/{team}/receipts` | ingest a receipt (bearer key); idempotent by id |
| `GET /teams/{team}/receipts` | the feed as JSON (bearer key); `?actor=&verdict=&contributor=&limit=` |
| `GET /teams/{team}/verify` | chain integrity (bearer key) |
| `GET /teams/{team}` | the web feed (asks for the key in the browser) |

Keys are supplied by whoever runs the hub, through `AGENTMEM_HUB_KEYS` (JSON) or the file at
`AGENTMEM_HUB_KEYS_FILE`. A team with no configured key can be neither written nor read.
