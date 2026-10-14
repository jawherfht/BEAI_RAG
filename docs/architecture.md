# Architecture

## Position in BEAI
Application layer → AI/ML microservices → LLM/NLP → **RAG + Knowledge Bases**. Called by the
Interaction Agents Service (Agents SDK / Streaming API) over gRPC, and by the Studio UI
(screen B) over REST/SSE through the API Gateway. Adds two stores missing from the platform's
Data & Persistence layer: **Knowledge / Vector DB (Qdrant)** and **Knowledge metadata DB
(PostgreSQL)**.

```
             API Gateway (JWT / API key, rate limits, credits)
                   │ REST · SSE · WS                 Interaction Agents Service
                   ▼                                         │ gRPC (mTLS, tenant in metadata)
            ┌──────────────┐◄────────────────────────────────┘
            │   rag-api    │── query path: cache → embed → hybrid search → (rerank) → LLM
            └──┬──┬──┬──┬──┘
     Postgres ◄┘  │  │  └► Redis (answer cache, counters)
     (metadata)   │  └───► RabbitMQ ──► ingestion-worker ── parse → chunk → embed → upsert
                  ▼                          │
               Qdrant ◄──────────────────────┘        MinIO/S3 (uploaded files)
          kb_chunks (dense + sparse)
```

## Implemented in Phase 1
- **Config** — `pydantic-settings`; env vars only (`.env` in dev). `CoreSettings` (shared) and
  `app.config.Settings` (rag-api), validated (threshold ordering, no HS256 in prod).
- **Auth context** — `app/auth.py`: tenant from a verified gateway JWT or a hashed API key;
  `agent_id` path → `TenantScope`, else 404 ([ADR 0006](decisions/0006-auth-context.md)).
- **Tenant isolation** — `beai_rag_core.qdrant_store.QdrantStore` is the only Qdrant caller;
  every tenant operation takes a `TenantScope` and adds the `tenant_id AND agent_id` filter
  ([ADR 0002](decisions/0002-shared-core-package.md)).
- **Qdrant `kb_chunks`** — named vectors `dense` (1024, cosine, HNSW m=16/ef_construct=100,
  int8 scalar quantization in RAM, originals on disk for rescoring) and `sparse` (BM25, IDF
  modifier). Keyword payload indexes `tenant_id` (`is_tenant: true`), `agent_id`,
  `source_id`, `lang`, created before any upsert. Deterministic point ids
  `uuid5(source_id:chunk_index:version)`.
- **Metadata DB** — SQLAlchemy 2 models + Alembic migration `0001`: `knowledge_bases`,
  `sources`, `ingestion_jobs`, `answers_log` with spec defaults and check constraints.
- **Health** — `/healthz` (liveness), `/readyz` (Qdrant collection, Postgres, Redis, RabbitMQ,
  object storage; concurrent, 2 s timeout each; 503 if any fails), `/metrics` (Prometheus).
  Embedder and LLM checks join `/readyz` in Phases 2 and 4.
- **Errors** — one JSON shape `{"error": {"code", "message", "details"}}` for every error.

## Latency rules (all phases)
Nothing slow on the live path: parsing, crawling, chunking, embedding are async via RabbitMQ.
Retrieval budget ≤ 60 ms p95; LLM TTFT ≤ 500 ms p95 (spec section 1.4).
