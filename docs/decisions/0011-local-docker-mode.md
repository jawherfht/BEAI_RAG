# ADR 0011 — Local Docker mode for manual tests (Windows)

Status: accepted (2026-10-17)

## Context
The product owner tests the module by hand on Windows with only Docker Desktop and Git (no WSL
shell, no uv, no Node). The dev workflow (`make`, uv on the host) does not fit.

## Decision
- `docker-compose.windows.yml` (project `beai-rag-local`, its own volumes) runs everything:
  infrastructure, a one-shot `migrate` service (Alembic + `app.bootstrap`), rag-api,
  ingestion-worker, the CPU embed-server and screen B. Only `127.0.0.1:3000` and
  `127.0.0.1:8000` are published.
- One local image for all Python services (`deploy/local/Dockerfile.python`, whole workspace,
  CPU-only torch): torch is stored once (≈ 3.6 GB image instead of three large ones).
  Production keeps the per-service images.
- LLM from the user's `.env` only (`LLM_*`, never committed): Google AI Studio's
  OpenAI-compatible endpoint with `gemini-3.8-flash` (GA 2026-09, Google's model docs) or Groq.
  Gemini 3 cannot disable thinking, so `LLM_REASONING_EFFORT` (new setting, default `none`)
  is `low`; the OpenAI-compat layer maps `reasoning_effort` to Gemini's thinking level.
- Re-ranker off by default (`RERANK_PROVIDER=none`); `RERANK_PROVIDER=local` in `.env` enables it.
- `DEV_AGENT_ID` makes http://localhost:3000 always open the same agent.
- Optional build secret `extra_ca` for TLS-intercepting proxies; `deploy/local/compose.test.yml`
  (mock LLM, CA, pre-seeded models) is for automated smoke tests only.

## Consequences
- First start downloads ≈ 6 GB of images/wheels and ≈ 3 GB of models; 16 GB RAM recommended.
- The local JWT secret and Qdrant key in the compose file are for this mode only; no database
  port is exposed.
- Gemini model names change often: if `gemini-3.8-flash` is retired, only `LLM_MODEL` changes.
