#!/usr/bin/env bash
# The cross-model pass: the two winning evals again with Sonnet as the action model.
#
# Everything positive so far ran on one self-hosted model, and "does it hold on the
# model people actually use" is the first fair question. This spends real API money,
# so it refuses to start unless that is acknowledged:
#
#   ANTHROPIC_API_KEY=... YES_SPEND=1 bash evals/run_sonnet.sh
#
# Rough cost at Sonnet prices: each repeat seed is 8 short sessions, each probe is
# 8 plus a probe call; expect a few dollars per block, under $10 for the default
# set. The memory model stays on the self-hosted endpoint when API_BASE is set, so
# the only billed tokens are the action agent's.
set -euo pipefail

MODEL="${MODEL:-claude-sonnet-4-6}"
API_BASE="${API_BASE:-http://localhost:8011/v1}"
MEMORY_MODEL="${MEMORY_MODEL:-litellm/hosted_vllm/Qwen/Qwen3.6-27B}"
SEEDS="${SEEDS:-1 2 3}"
OUT="${OUT:-evals/report}"
SCRATCH="${SCRATCH:-$(mktemp -d)}"

[ -n "${ANTHROPIC_API_KEY:-}" ] || { echo "set ANTHROPIC_API_KEY (rotate the old one first)"; exit 1; }
[ "${YES_SPEND:-}" = "1" ] || { echo "this bills real tokens; set YES_SPEND=1 to confirm"; exit 1; }
curl -fsS -m 5 "$API_BASE/models" -H "Authorization: Bearer ${VLLM_API_KEY:-agentmem-local}" \
    >/dev/null || { echo "no self-hosted endpoint at $API_BASE for the memory model"; exit 1; }

echo "== repeat, ${SEEDS// /,} seeds, action=$MODEL memory=$MEMORY_MODEL"
for s in $SEEDS; do
    uv run python evals/repeat/run_repeat.py \
        --tickets evals/repeat/tickets/click-bitrot.json \
        --action-model "$MODEL" --memory-model "$MEMORY_MODEL" --api-base "$API_BASE" \
        --keep-dir "$SCRATCH/repeat-sonnet-$s" \
        --out "$OUT/repeat-click-sonnet-s$s.json"
done

echo "== probe, click and more-itertools"
for t in click more-itertools; do
    uv run python evals/realworld/run_probe.py \
        --tickets "evals/realworld/tickets/$t.json" \
        --action-model "$MODEL" --memory-model "$MEMORY_MODEL" --api-base "$API_BASE" \
        --keep-dir "$SCRATCH/probe-sonnet-$t" \
        --out "$OUT/realworld-probe-sonnet-$t.json"
done

echo
echo "done. Add the new artifacts to check_receipts.py CLAIMS before quoting any of it."
