# BEAI Studio — Knowledge Base & RAG module

Makes a live BEAI avatar answer **only from the customer's own documents**, with a citation
(file + page) and a confidence level, fast enough for spoken conversation.
The full specification is [`BEAI_RAG_BUILD_SPEC.md`](BEAI_RAG_BUILD_SPEC.md); working rules
for contributors and agents are in [`CLAUDE.md`](CLAUDE.md).

## Status

| Phase | Scope | State |
|---|---|---|
| 1 Foundations | skeleton, compose, config, auth, DB + migrations, Qdrant collection, health, CI | **done — awaiting review** |
| 2 Ingestion | upload/URL/business-info, worker, parse → chunk → embed → upsert | not started |
| 3 Retrieval | hybrid search, tenant filter, re-ranker, confidence, cache | not started |
| 4 Generation | prompt, LLM streaming, citations, SSE/WS, gRPC | not started |
| 5 Screen B UI | Next.js page + status chip | not started |
| 6 Evaluation | datasets, calibration, reports | not started |
| 7 Hardening | observability, security, Helm, load tests | not started |

## Quick start (dev)

Requirements: Docker with Compose v2, [uv](https://docs.astral.sh/uv/), GNU make.

1. `cp .env.example .env` (done automatically by `make up`)
2. `make up` — starts Qdrant, Postgres, Redis, RabbitMQ, MinIO; runs migrations; creates the
   `kb_chunks` collection with payload indexes and the object-storage bucket
3. `make test` — unit + integration tests (integration tests start their own containers)
4. `make run-api` — API on http://localhost:8000 (`/healthz`, `/readyz`, `/metrics`, `/docs`)
5. `make phase1-check` — prints `/readyz` and the Qdrant collection config

Other targets: `make lint`, `make typecheck`, `make show-collection`, `make openapi`,
`make licenses`, `make down`.

## Layout

```
packages/beai_rag_core/   shared: enums, TenantScope, Qdrant store (single tenant-filter point), DB models
services/rag-api/         FastAPI app (app/), Alembic migrations (app/db/alembic), Dockerfile
services/ingestion-worker/ queue consumer (Phase 2)
proto/beai/rag/v1/        gRPC contract for the Interaction Agents Service
tests/unit, tests/integration
docs/                     architecture, API, ADRs (docs/decisions)
```

## Documentation
- [Architecture](docs/architecture.md)
- [API](docs/api.md) (OpenAPI: [`docs/openapi.json`](docs/openapi.json))
- [Decisions (ADRs)](docs/decisions/)
