#!/usr/bin/env bash
# Serve an open-weights model for the evals. Run this ON the GPU box.
#
#   MODEL=Qwen/Qwen3.6-27B ./serve_vllm.sh
#
# The eval drives the model through tool calls, so the parsers matter more than
# anything else here: get them wrong and every turn comes back as prose and the
# whole run is wasted. The defaults follow the Qwen3.6 model card; a different
# model almost certainly wants different ones, so check its card and override.
# check_endpoint.py verifies the result before you spend GPU hours on it.
set -euo pipefail

MODEL="${MODEL:-Qwen/Qwen3.6-27B}"
PORT="${PORT:-8000}"
PARSER="${PARSER:-qwen3_coder}"        # `vllm serve --help=Frontend` lists valid names
REASONING_PARSER="${REASONING_PARSER:-qwen3}"   # Qwen3.6 thinks by default
MAX_LEN="${MAX_LEN:-32768}"            # native is 262144; this is plenty per trial
GPU_FRAC="${GPU_FRAC:-0.92}"
KEY="${VLLM_API_KEY:-agentmem-local}"

command -v vllm >/dev/null || {
    echo "installing vllm..."
    pip install --quiet vllm
}

echo "serving $MODEL on :$PORT"
echo "  tool-call-parser=$PARSER  reasoning-parser=$REASONING_PARSER  max_model_len=$MAX_LEN"

args=(
    serve "$MODEL"
    --host 0.0.0.0
    --port "$PORT"
    --api-key "$KEY"
    --enable-auto-tool-choice
    --tool-call-parser "$PARSER"
    --max-model-len "$MAX_LEN"
    --gpu-memory-utilization "$GPU_FRAC"
)
[ -n "$REASONING_PARSER" ] && args+=(--reasoning-parser "$REASONING_PARSER")

exec vllm "${args[@]}"
