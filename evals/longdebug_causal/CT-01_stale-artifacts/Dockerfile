FROM python:3.11-slim

WORKDIR /work
RUN pip install --no-cache-dir pytest
COPY repo/ /work/

CMD ["python", "-m", "pytest", "-q"]
