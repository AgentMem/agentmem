#!/usr/bin/env bash
# Turn a bare vast.ai VM instance into a box that can run the whole eval by itself.
#
#   ssh root@<vm> 'bash -s' < evals/vm/bringup.sh
#   # or, on the box:
#   bash bringup.sh
#
# Why a VM and not the usual Docker instance: Terminal-Bench starts a container per
# task, so the harness needs a Docker daemon of its own. A vast Docker instance is
# itself a container and running Docker inside one is a fight. A vast VM instance
# (rent with the "VM instances" filter, image docker.io/vastai/kvm:*) is a real KVM
# guest with systemd, so Docker installs the ordinary way.
#
# What that buys: the harness stops living on a laptop that can only feed two trials
# at once while the GPU idles at 0% and bills anyway. Everything runs on one box,
# talks to vLLM over localhost, and keeps running after you shut the laptop.
#
# This script is idempotent. Run it again after a reboot.
set -euo pipefail

MODEL="${MODEL:-Qwen/Qwen3.6-27B}"
PORT="${PORT:-8000}"
WORK="${WORK:-/workspace}"
TAU2_REF="${TAU2_REF:-main}"

say() { printf '\n=== %s\n' "$*"; }

say "sanity: is this actually a VM instance?"
# A Docker instance has no systemd, and everything below would fail in a way that
# looks like a network problem an hour later. Say so now instead.
if ! pidof systemd >/dev/null 2>&1 && [ ! -d /run/systemd/system ]; then
    echo "ERROR: no systemd. This looks like a vast *Docker* instance, not a VM."
    echo "       Docker-in-Docker will not work here. Destroy it and rent again with"
    echo "       the 'VM instances' filter (image docker.io/vastai/kvm:*)."
    exit 1
fi
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader || {
    echo "ERROR: no GPU visible. Check the VM has the driver passed through."
    exit 1
}
echo "host RAM: $(free -g | awk '/^Mem:/{print $2}') GiB (need >= 64 for -n 8..12)"

say "docker"
if ! command -v docker >/dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable --now docker
fi
docker run --rm hello-world >/dev/null && echo "docker works inside the VM"

say "uv"
command -v uv >/dev/null || { curl -LsSf https://astral.sh/uv/install.sh | sh; }
export PATH="$HOME/.local/bin:$PATH"

say "agentmem"
mkdir -p "$WORK" && cd "$WORK"
[ -d AgentMem ] || git clone -q https://github.com/AgentMem/agentmem.git AgentMem
cd AgentMem && git pull -q --ff-only || true
uv sync -q
uv run pytest -q 2>&1 | tail -1

say "tau2-bench (needs python 3.12, not 3.13)"
# Its pyproject says >=3.12,<3.14, but the voice path imports `audioop`, which PEP 594
# removed in 3.13. On 3.13 `import tau2` dies before anything runs. Pin 3.12.
cd "$WORK"
[ -d tau2-bench ] || git clone -q https://github.com/sierra-research/tau2-bench.git
cd tau2-bench && git checkout -q "$TAU2_REF" && git pull -q --ff-only || true
[ -d .venv-tau2 ] || uv venv -q --python 3.12 .venv-tau2
VIRTUAL_ENV="$PWD/.venv-tau2" uv pip install -q -e . pytest
VIRTUAL_ENV="$PWD/.venv-tau2" uv pip install -q "$WORK/AgentMem/packages/agentmem" "$WORK/AgentMem/evals"
# NOTE: `pip install tau2` from PyPI is a completely unrelated package by another
# author. The benchmark is only on GitHub.

say "harbor (terminal-bench 2.0)"
cd "$WORK"
[ -d harborenv ] || uv venv -q harborenv
VIRTUAL_ENV="$PWD/harborenv" uv pip install -q harbor==0.18.0
[ -d tb2 ] || git clone -q https://github.com/laude-institute/terminal-bench.git tb2 || true

say "vLLM"
if curl -fsS -m 3 "http://localhost:$PORT/v1/models" -H "Authorization: Bearer ${VLLM_API_KEY:-agentmem-local}" >/dev/null 2>&1; then
    echo "already serving on :$PORT"
else
    # The template may ship its own vLLM holding the whole card. Ours cannot start
    # next to it.
    for pid in $(nvidia-smi --query-compute-apps=pid --format=csv,noheader); do
        echo "killing pid $pid, which is holding VRAM"
        kill -9 "$pid" 2>/dev/null || true
    done
    sleep 5
    cd "$WORK/AgentMem"
    MODEL="$MODEL" PORT="$PORT" MAX_LEN=131072 \
        nohup bash evals/tbench/serve_vllm.sh > "$WORK/serve.log" 2>&1 &
    echo "starting vLLM, first run downloads ~54GB; watch $WORK/serve.log"
    for _ in $(seq 1 120); do
        curl -fsS -m 3 "http://localhost:$PORT/v1/models" \
            -H "Authorization: Bearer ${VLLM_API_KEY:-agentmem-local}" >/dev/null 2>&1 && break
        sleep 30
    done
fi

say "prove tool calling works before spending GPU hours on it"
cd "$WORK/AgentMem"
uv run python evals/tbench/check_endpoint.py \
    --model "litellm/hosted_vllm/$MODEL" \
    --api-base "http://localhost:$PORT/v1" --no-thinking

say "prove the tau2 adapter is wired, with no model involved"
cd "$WORK/AgentMem"
"$WORK/tau2-bench/.venv-tau2/bin/python" evals/tau2/check_adapter.py 2>&1 | tail -4

cat <<EOF

Ready. Both benchmarks run from this box now.

  tau2, one domain, both arms (the memory arm is forced to one ticket at a time):
    cd $WORK/AgentMem
    $WORK/tau2-bench/.venv-tau2/bin/python evals/tau2/run_live.py \\
        --domain airline --action-model litellm/hosted_vllm/$MODEL \\
        --api-base http://localhost:$PORT/v1 --no-thinking \\
        --out $WORK/tau2-airline.json

  terminal-bench, full suite, the concurrency a laptop could not reach:
    uv run python evals/tbench/run_live.py \\
        --action-model litellm/hosted_vllm/$MODEL \\
        --api-base http://localhost:$PORT/v1 \\
        --tb-dir $WORK/tb2/terminal-bench --harbor-bin $WORK/harborenv/bin/harbor \\
        --jobs-dir $WORK/tb-jobs -n 8

Run them at once. Terminal-Bench spends most of its time waiting on containers and
tau2 spends all of its on the GPU, so together they keep the card busy instead of
paying it to idle.

The meter is running. Stop the instance from the vast console when the runs finish.
EOF
