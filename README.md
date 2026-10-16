# BEAI Studio — Knowledge Base & RAG module

Makes a live BEAI avatar answer **only from the customer's own documents**, with a citation
(file + page) and a confidence level, fast enough for spoken conversation.
The full specification is [`BEAI_RAG_BUILD_SPEC.md`](BEAI_RAG_BUILD_SPEC.md); working rules
for contributors and agents are in [`CLAUDE.md`](CLAUDE.md).

## Status

| Phase | Scope | State |
|---|---|---|
| 1 Foundations | skeleton, compose, config, auth, DB + migrations, Qdrant collection, health, CI | **done** |
| 2 Ingestion | upload/URL/business-info, worker, parse → chunk → embed → upsert | **done — acceptance PASS with real models; 50-page CPU benchmark over budget, see [report](eval/reports/phase2-ingestion-benchmark.md)** |
| 3 Retrieval | hybrid search, tenant filter, re-ranker, confidence, cache | **done — recall@4 0.98, MRR@10 0.948 on KB #1; isolation suite green; search p95 29 ms (embedding latency needs the GPU pool)** |
| 4 Generation | prompt, LLM streaming, citations, SSE/WS, gRPC | **done — acceptance PASS (Qwen3.8-27B via Groq in dev); TTFT on GPU pending, see checklist** |
| 5 Screen B UI | Next.js page + status chip | **done — Playwright E2E passes against the real stack** |
| 6 Evaluation | datasets, calibration, reports | not started |
| 7 Hardening | observability, security, Helm, load tests | not started |

## Quick start (dev)

Requirements: Docker with Compose v2, [uv](https://docs.astral.sh/uv/), GNU make.

1. `cp .env.example .env` (done automatically by `make up`)
2. `make up` — starts Qdrant, Postgres, Redis, RabbitMQ, SeaweedFS (S3); runs migrations; creates the
   `kb_chunks` collection with payload indexes and the object-storage bucket
3. `make test` — unit + integration tests (integration tests start their own containers)
4. `make run-api` — API on http://localhost:8000 (`/healthz`, `/readyz`, `/metrics`, `/docs`)
5. `make run-embedder` (CPU embedding server, `EMBED_PROVIDER=local`, `EMBED_URL=http://localhost:8080`)
   and `make run-worker` — the ingestion worker (models download from Hugging Face on first use)
6. `make phase1-check` / `make phase2-check` — acceptance checks of each phase

Screen B: `make web-install`, then `make e2e` (starts rag-api, worker and embed-server, builds the
UI and runs Playwright) or `cd web/knowledge-base-ui && npm run dev` → http://localhost:3000.

Evaluation: `make phase4-check` (sample question end to end), `make calibrate` (thresholds),
`make eval-retrieval` (KB #1 recall@4 / MRR@10 / latency; add `ARGS=--rerank`).

Other targets: `make lint`, `make typecheck`, `make show-collection`, `make openapi`,
`make sample-data`, `make licenses`, `make down`.

## Layout

```
packages/beai_rag_core/   shared: TenantScope, Qdrant store (single tenant-filter point), DB models +
                          repositories, queue topology, S3 storage, embedder clients
services/rag-api/         FastAPI app (app/), Alembic migrations (app/db/alembic), Dockerfile
web/knowledge-base-ui/    Next.js screen B + <KnowledgeBaseStatusChip>
services/ingestion-worker/ queue consumer: Docling/crawler → chunker → embed → Qdrant
proto/beai/rag/v1/        gRPC contract for the Interaction Agents Service
tests/unit, tests/integration
docs/                     architecture, API, ADRs (docs/decisions)
```

## Documentation
- **[Before production](docs/before-production.md)** — GPU items still to confirm
- [Architecture](docs/architecture.md)
- [API](docs/api.md) (OpenAPI: [`docs/openapi.json`](docs/openapi.json))
- [Decisions (ADRs)](docs/decisions/)
