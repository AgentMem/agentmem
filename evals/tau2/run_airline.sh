#!/usr/bin/env bash
# tau2-bench airline, both arms, on the self-hosted endpoint. Run after connect.sh.
#
#   bash evals/tau2/run_airline.sh          # the whole airline split
#   NUM_TASKS=8 bash evals/tau2/run_airline.sh   # a pilot first
#
# Costs nothing per token: the agent, the user simulator and the memory layer all go
# to the same local vLLM. The GPU bills by the hour regardless, which is the only
# reason to care how long this takes.
set -euo pipefail

PORT="${PORT:-8011}"
MODEL="${MODEL:-Qwen/Qwen3.6-27B}"
NUM_TASKS="${NUM_TASKS:-0}"        # 0 runs the whole split
SEED_TAG="${SEED_TAG:-s1}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PY="$REPO/tau2-bench/.venv-tau2/bin/python"
OUT="$REPO/evals/report/tau2-airline-$SEED_TAG.json"
LOG="$REPO/evals/report/tau2-airline-$SEED_TAG.log"

[ -x "$PY" ] || { echo "no tau2 venv at $PY (see evals/tau2/README.md)"; exit 1; }

export HOSTED_VLLM_API_KEY="${VLLM_API_KEY:-agentmem-local}"
export OPENAI_API_KEY="${VLLM_API_KEY:-agentmem-local}"

curl -fsS -m 5 "http://localhost:$PORT/v1/models" -H "Authorization: Bearer $HOSTED_VLLM_API_KEY" \
    >/dev/null || { echo "nothing serving on localhost:$PORT. Run connect.sh first."; exit 1; }

mkdir -p "$REPO/evals/report"
echo "airline, both arms, $( [ "$NUM_TASKS" = 0 ] && echo "whole split" || echo "$NUM_TASKS tickets" )"
echo "log:    $LOG"
echo "report: $OUT"
echo

# caffeinate so shutting the laptop lid does not kill the run while the GPU keeps
# billing; nohup so it survives this terminal. Watch it with:  tail -f "$LOG"
caffeinate -dimsu nohup "$PY" "$REPO/evals/tau2/run_live.py" \
    --domain airline \
    --action-model "litellm/hosted_vllm/$MODEL" \
    --api-base "http://localhost:$PORT/v1" \
    --no-thinking \
    --num-tasks "$NUM_TASKS" \
    --seed-tag "$SEED_TAG" \
    --state-dir "$REPO/evals/report/tau2-state" \
    --out-dir "$REPO/evals/report/tau2-runs" \
    --out "$OUT" \
    > "$LOG" 2>&1 &

echo "started (pid $!). Follow it with:"
echo "  tail -f $LOG"
echo
echo "The baseline arm runs first and in parallel. The memory arm runs one ticket at a"
echo "time by design, so it takes longer; that is not a hang."
echo "Stop the vast instance when the report lands."
