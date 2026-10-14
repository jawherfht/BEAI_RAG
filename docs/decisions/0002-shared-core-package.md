# ADR 0002 — Shared `beai_rag_core` package holds the Qdrant store and DB models

Status: accepted (Phase 1)

The spec puts the tenant-filter in `services/rag-api/app/retrieval/qdrant_store.py` and the
SQLAlchemy models in `services/rag-api/app/db/`. The ingestion worker must also upsert and
delete points and update `sources` rows.

**Decision.** The implementation lives in `packages/beai_rag_core/beai_rag_core/qdrant_store.py`
and `beai_rag_core/db/models.py` (spec section 3: "shared code ... qdrant helpers"). The
spec paths in rag-api re-export them. There is still exactly **one** module that talks to
Qdrant; `tests/unit/test_no_raw_qdrant_calls.py` fails if any other module imports
`qdrant_client` or calls a point-level client method.

Every tenant operation (`upsert`, `count`, `scroll`, `delete_source`, and `search` in Phase 3)
requires a `TenantScope(tenant_id: UUID, agent_id: UUID)`. `upsert` overwrites
`tenant_id`/`agent_id` in the payload from the scope and rejects payloads that disagree.

Tiered multitenancy: `CollectionSpec` carries shard settings so promoting a large tenant to
a dedicated shard is a config change.
