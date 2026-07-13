FROM python:3.11-slim

WORKDIR /workspace

RUN pip install --no-cache-dir pytest

# Only the repo lands in the agent workspace. The hidden verifier is mounted by
# the harness at scoring time and never baked into this image.
COPY repo/ /workspace/

ENV PYTHONPATH=/workspace
ENV PYTHONDONTWRITEBYTECODE=1
