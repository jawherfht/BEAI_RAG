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
               Qdrant ◄──────────────────────┘     S3 / SeaweedFS (files)
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

## Implemented in Phase 2 — ingestion (async, off the live path)
See [ADR 0007](decisions/0007-ingestion-pipeline.md) for the decisions.

```
POST /sources/files|urls|business-info
  └─ validate (sniff type, size, zip bomb, macros) → S3 put → sources+job rows → commit
     → publish ingest.index → 202
ingestion-worker  (beai.ingest → ingest.index|reindex|delete|recrawl)
  parsing    Docling (PDF/DOCX/PPTX/HTML/MD, page provenance, tables as Markdown, OCR)
             | polite crawler + Trafilatura (URLs) | business-info renderer
             → parsed-document cache (_parsed.json) → language (lingua)
  chunking   structure-aware, token-based (embedding tokenizer)
  embedding  [optional contextual prefix via LLM] → dense (TEI / vLLM) + BM25 (FastEmbed)
  upsert     Qdrant batches of 128 → delete stale points (blue/green) → ready, kb_version+1
  failures   transient: retry 2 s / 8 s / 32 s → ingest.dead; permanent: error at once
```

- **API**: `GET/PUT /knowledge-base` (settings; a chunk-size change re-indexes every source of the
  agent), `GET /knowledge-base/status` (Persona Builder label), sources upload / list / delete /
  reindex. All writes return 202.
- **Shared core** (`beai_rag_core`): repositories (every query scoped by tenant + agent), queue
  topology and publisher, S3 storage with tenant-prefixed keys, embedder interfaces
  (`DenseEmbedder`, `SparseEncoder`, `TokenCounter`) chosen by config.
- **Payload** of each point: `tenant_id, agent_id, knowledge_base_id, source_id, source_type,
  file_name, url, title, page, page_end, section, chunk_index, text, context_prefix, lang,
  embed_model, kb_version, created_at`.

## Implemented in Phase 3 — retrieval (live path)
See [ADR 0008](decisions/0008-retrieval.md).

```
question ─► cache (tenant|agent|kb_version|normalised q) ─hit─► result
          └► embed query (card prompt) ∥ BM25 query vector
             ► Qdrant Query API: prefetch dense(50) + sparse(50), tenant+agent filter,
               agent-scoped IDF, RRF fusion → top_k (or 50 if re-ranking)
             ► [re-rank with Qwen3-Reranker if enabled and ≥ 10 candidates] → top_k
             ► grounding: best cosine (or re-rank score) < threshold → fallback, no LLM
             ► confidence bucket high / medium / low
```

`app/retrieval/` (retriever, confidence, re-ranker clients), `app/cache/answer_cache.py`,
`app/services/retrieval.py` (KB settings + cache + retriever, used by `/test`, `/answer` and
gRPC in Phase 4). `/readyz` now also checks the embedder.

## Implemented in Phase 4 — generation
See [ADR 0009](decisions/0009-generation.md).

```
/test · /answer (SSE) · /ws · gRPC Answer
  └─ AnswerService: answer cache ─hit─► replay
       └► retrieval (Phase 3) ─below threshold─► fallback message (LLM not called)
       └► prompt (persona + grounding rules + numbered CONTEXT) ─► LLM stream (OpenAI-compatible:
          vLLM in prod, Groq in dev; thinking off; 429 retry) ─► tokens {text, spoken}
       └► citations [n] → sources; fallback / no-citation checks; confidence
       └► cache · usage.events · sampled PII-scrubbed answers_log · metrics (background)
```

Thresholds come from `config/thresholds.<embed model>.json` (`eval/calibrate.py`).

## Implemented in Phase 5 — screen B
See [ADR 0010](decisions/0010-frontend.md). `web/knowledge-base-ui` (Next.js): browser →
`/api/rag/*` (Next route handler, allow-listed paths, streams uploads and SSE, adds auth) →
rag-api. Screen B sections: warning banner, sources ("Ground answers in": drop zone, + Add URL,
Business info, status pills, delete, "3 files, 2 URLs"), retrieval settings (chunk size,
top-k, fallback, hybrid / re-ranking / RAG toggles), "Test this agent" (streamed answer,
`file p.N` chips with snippets, confidence badge, latency), Save & Continue → Persona Builder
with `<KnowledgeBaseStatusChip>`. Screenshots: `docs/screens/`.

## Latency rules (all phases)
Nothing slow on the live path: parsing, crawling, chunking, embedding are async via RabbitMQ.
Retrieval budget ≤ 60 ms p95; LLM TTFT ≤ 500 ms p95 (spec section 1.4).
