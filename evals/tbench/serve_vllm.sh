#!/usr/bin/env bash
# Serve an open-weights model for the evals. Run this ON the GPU box.
#
#   MODEL=Qwen/Qwen3.6-27B ./serve_vllm.sh
#
# The eval drives the model through tool calls, so the tool-call parser matters more
# than anything else here: get it wrong and every turn comes back as prose and the
# whole run is wasted. check_endpoint.py verifies that before you spend GPU hours.
set -euo pipefail

MODEL="${MODEL:-Qwen/Qwen3.6-27B}"
PORT="${PORT:-8000}"
PARSER="${PARSER:-hermes}"          # Qwen chat models use hermes; check your model card
MAX_LEN="${MAX_LEN:-32768}"         # room for a long instruction plus a trimmed window
GPU_FRAC="${GPU_FRAC:-0.92}"
KEY="${VLLM_API_KEY:-agentmem-local}"

command -v vllm >/dev/null || {
    echo "installing vllm..."
    pip install --quiet vllm
}

echo "serving $MODEL on :$PORT (parser=$PARSER, max_model_len=$MAX_LEN)"
exec vllm serve "$MODEL" \
    --host 0.0.0.0 \
    --port "$PORT" \
    --api-key "$KEY" \
    --enable-auto-tool-choice \
    --tool-call-parser "$PARSER" \
    --max-model-len "$MAX_LEN" \
    --gpu-memory-utilization "$GPU_FRAC" \
    --disable-log-requests
