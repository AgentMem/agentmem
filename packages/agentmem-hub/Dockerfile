# Build from the repo root as context: `docker build -f packages/agentmem-hub/Dockerfile .`
FROM python:3.12-slim

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY packages/agentmem ./packages/agentmem
COPY packages/agentmem-hub ./packages/agentmem-hub
# Install the local core first so the hub's agentmem-core dependency resolves to it.
RUN uv pip install --system --no-cache ./packages/agentmem ./packages/agentmem-hub

ENV AGENTMEM_HUB_HOST=0.0.0.0 \
    AGENTMEM_HUB_PORT=8791 \
    AGENTMEM_HUB_DATA=/data
VOLUME /data
EXPOSE 8791

# Teams, keys, and billing secrets come from the environment at run time, never baked in.
CMD ["agentmem-hub"]
