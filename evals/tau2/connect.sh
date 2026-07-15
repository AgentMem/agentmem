#!/usr/bin/env bash
# Point this Mac at a freshly started vast box and get vLLM answering on localhost.
#
#   bash evals/tau2/connect.sh 'ssh -p 12345 root@1.2.3.4 -L 8080:localhost:8080'
#
# Paste the SSH line straight from the vast console. Stopping and starting an instance
# usually changes its port and sometimes its host, so last session's line is likely
# wrong; the script only reads the port and host out of whatever you paste.
#
# Safe to re-run. If vLLM is already up it just re-checks and exits.
set -euo pipefail

SSH_LINE="${1:-}"
PORT="${PORT:-8011}"          # local port; the tunnel maps it to the same port remotely
MODEL="${MODEL:-Qwen/Qwen3.6-27B}"
KEY="${VLLM_API_KEY:-agentmem-local}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

[ -n "$SSH_LINE" ] || { echo "usage: bash evals/tau2/connect.sh '<the ssh line from vast>'"; exit 1; }

RPORT="$(sed -nE 's/.*-p[[:space:]]*([0-9]+).*/\1/p' <<<"$SSH_LINE")"
RHOST="$(grep -oE 'root@[0-9a-zA-Z._-]+' <<<"$SSH_LINE" | head -1)"
[ -n "$RPORT" ] && [ -n "$RHOST" ] || { echo "could not read a port and host out of: $SSH_LINE"; exit 1; }
SSH=(ssh -o StrictHostKeyChecking=accept-new -p "$RPORT" "$RHOST" -i "$HOME/.ssh/id_ed25519")

say() { printf '\n=== %s\n' "$*"; }

say "reachable?"
"${SSH[@]}" -o ConnectTimeout=15 'echo ok; nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader' \
    || { echo "cannot reach $RHOST:$RPORT. Is the instance finished starting?"; exit 1; }

say "is the model still on the disk, or is this a fresh box?"
"${SSH[@]}" 'du -sh ~/.cache/huggingface 2>/dev/null || echo "no HF cache: expect a ~54GB download"'

say "vLLM on the box"
"${SSH[@]}" bash -s <<REMOTE
set -e
if curl -fsS -m 3 http://localhost:$PORT/v1/models -H "Authorization: Bearer $KEY" >/dev/null 2>&1; then
    echo "already serving on :$PORT"
    exit 0
fi
# Anything else holding the card has to go first; 27B needs essentially all of it.
for pid in \$(nvidia-smi --query-compute-apps=pid --format=csv,noheader); do
    echo "killing pid \$pid, holding VRAM"; kill -9 "\$pid" 2>/dev/null || true
done
sleep 5
cd /workspace/AgentMem 2>/dev/null || {
    mkdir -p /workspace && cd /workspace
    git clone -q https://github.com/AgentMem/agentmem.git AgentMem && cd AgentMem
}
git pull -q --ff-only 2>/dev/null || true
PATH=/usr/local/bin:\$PATH PORT=$PORT MAX_LEN=131072 \
    nohup bash evals/tbench/serve_vllm.sh > /workspace/serve$PORT.log 2>&1 &
echo "vLLM starting; tail /workspace/serve$PORT.log"
REMOTE

say "tunnel localhost:$PORT to the box"
pkill -f "ssh -fN -p .* -L $PORT:localhost:$PORT" 2>/dev/null || true
ssh -fN -o StrictHostKeyChecking=accept-new -p "$RPORT" "$RHOST" -i "$HOME/.ssh/id_ed25519" \
    -L "$PORT:localhost:$PORT"
echo "tunnel up (pid $(pgrep -f "ssh -fN -p $RPORT" | head -1))"

say "waiting for the model to load (first run also downloads it)"
for i in $(seq 1 120); do
    if curl -fsS -m 3 "http://localhost:$PORT/v1/models" -H "Authorization: Bearer $KEY" >/dev/null 2>&1; then
        echo "serving after ~$((i * 15))s"; break
    fi
    sleep 15
    [ $((i % 8)) -eq 0 ] && "${SSH[@]}" "tail -1 /workspace/serve$PORT.log" 2>/dev/null || true
done

say "prove tool calling works before spending an hour on it"
cd "$REPO"
# litellm reads the key from the environment for a hosted_vllm route; without these
# the check fails with Unauthorized against a server that is working perfectly.
export HOSTED_VLLM_API_KEY="$KEY"
export OPENAI_API_KEY="$KEY"
uv run python evals/tbench/check_endpoint.py \
    --model "litellm/hosted_vllm/$MODEL" \
    --api-base "http://localhost:$PORT/v1" --no-thinking

cat <<EOF

Ready. Next:

  bash evals/tau2/run_airline.sh

The meter is running from the moment the instance started, whether or not anything is
using the card. Stop it from the vast console when the run finishes.
EOF
