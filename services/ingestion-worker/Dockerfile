# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base
RUN pip install --no-cache-dir uv==0.11.32
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /src
COPY pyproject.toml uv.lock ./
COPY packages packages
COPY services services
RUN uv sync --frozen --no-dev --package beai-ingestion-worker
ENV PATH=/opt/venv/bin:$PATH \
    HF_HOME=/models/hf \
    FASTEMBED_CACHE_PATH=/models/fastembed
WORKDIR /src/services/ingestion-worker
RUN useradd --uid 10001 --create-home app && mkdir -p /models && chown app /models
USER app
CMD ["python", "-m", "worker.main"]
