#!/usr/bin/env bash
# The cross-model pass: the winning evals again with Sonnet as the action model.
#
# Everything positive so far ran on one self-hosted model, and "does it hold on the
# model people actually use" is the first fair question. This bills real API tokens
# for the action agent, and by default a cheap Anthropic model for the memory step,
# so no GPU box is needed. The rotated key is the only requirement.
#
#   ANTHROPIC_API_KEY=... YES_SPEND=1 bash evals/run_sonnet.sh
#
# Cost: only the action agent is billed. A tight per-session cap (default $0.50)
# bounds a runaway; realistic total for the default set is a few dollars. A one-call
# preflight spends about a tenth of a cent to prove auth and the model id before any
# of the long loops start.
set -euo pipefail

MODEL="${MODEL:-claude-sonnet-4-6}"
API_BASE="${API_BASE:-}"
MEMORY_MODEL="${MEMORY_MODEL:-claude-haiku-4-5}"  # boxless; set to litellm/hosted_vllm/... + API_BASE to use a GPU
SEEDS="${SEEDS:-1 2 3}"
CAP="${CAP:-0.50}"            # per action-session USD cap; the loop stops at it
OUT="${OUT:-evals/report}"
SCRATCH="${SCRATCH:-$(mktemp -d)}"

[ -n "${ANTHROPIC_API_KEY:-}" ] || { echo "set ANTHROPIC_API_KEY (rotate the old one first)"; exit 1; }
[ "${YES_SPEND:-}" = "1" ] || { echo "this bills real tokens; set YES_SPEND=1 to confirm"; exit 1; }
[ -z "$API_BASE" ] || curl -fsS -m 5 "$API_BASE/models" -H "Authorization: Bearer ${VLLM_API_KEY:-agentmem-local}" \
    >/dev/null || { echo "API_BASE set but no endpoint at $API_BASE"; exit 1; }

echo "== preflight: one real Sonnet call (about \$0.001) to prove auth and the model id"
uv run python - "$MODEL" <<'PY'
import sys
from agentmem.llm.anthropic import AnthropicProvider

reply = AnthropicProvider(model=sys.argv[1], timeout=60.0).complete(
    system="Reply with the single word ok.",
    messages=[{"role": "user", "content": "ok"}],
    max_tokens=8,
)
text = (reply.text or "").strip()
print(f"  reply: {text[:40]!r}  tokens in/out: {reply.usage.input_tokens}/{reply.usage.output_tokens}")
if not text:
    sys.exit("preflight got an empty reply; stopping before the billed loops run")
PY

echo "== repeat, ${SEEDS// /,} seeds, action=$MODEL memory=$MEMORY_MODEL, cap \$$CAP/session"
for s in $SEEDS; do
    uv run python evals/repeat/run_repeat.py \
        --tickets evals/repeat/tickets/click-bitrot.json \
        --action-model "$MODEL" --memory-model "$MEMORY_MODEL" ${API_BASE:+--api-base "$API_BASE"} \
        --session-usd-cap "$CAP" \
        --keep-dir "$SCRATCH/repeat-sonnet-$s" \
        --out "$OUT/repeat-click-sonnet-s$s.json"
done

echo "== probe, click and more-itertools"
for t in click more-itertools; do
    uv run python evals/realworld/run_probe.py \
        --tickets "evals/realworld/tickets/$t.json" \
        --action-model "$MODEL" --memory-model "$MEMORY_MODEL" ${API_BASE:+--api-base "$API_BASE"} \
        --session-usd-cap "$CAP" \
        --keep-dir "$SCRATCH/probe-sonnet-$t" \
        --out "$OUT/realworld-probe-sonnet-$t.json"
done

echo
echo "done. Add the new artifacts to check_receipts.py CLAIMS before quoting any of it,"
echo "no GPU box to stop in the default boxless setup."
