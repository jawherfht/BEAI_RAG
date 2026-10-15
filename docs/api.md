# API

All REST endpoints except health live under `/v1`. Authentication comes from the API
Gateway: `Authorization: Bearer <JWT>` or `X-API-Key: <key>`. The tenant is taken only from
those credentials. An `agent_id` the caller may not use returns **404**.

Machine-readable schema: [`openapi.json`](openapi.json) (regenerate with `make openapi`;
`tests/unit/test_openapi_snapshot.py` fails if it is stale).

## Error shape
```json
{"error": {"code": "not_found", "message": "Agent not found", "details": {}}}
```
Codes in use: `unauthorized` (401), `not_found` (404), `conflict` (409),
`payload_too_large` (413), `unsupported_media_type` (415), `validation_error` (422),
`internal_error` (500), `service_unavailable` (503).

## Health (Phase 1)

| Method & path | Response |
|---|---|
| `GET /healthz` | `200 {"status": "ok"}` — process is alive |
| `GET /readyz` | `200` or `503` `{"status": "ok"\|"unavailable", "checks": {"qdrant"\|"postgres"\|"redis"\|"rabbitmq"\|"object_storage": {"ok": bool, "latency_ms": float, "error"?: str}}}` |
| `GET /metrics` | Prometheus text format |

## Knowledge base (Phase 2)

| Method & path | Body | Response |
|---|---|---|
| `GET /v1/agents/{agent_id}/knowledge-base` | — | `200` settings + `counts{files, urls, business_info}` + `status` + `kb_version`. Before the first PUT/upload the defaults are returned (`status: "empty"`, nothing is created). |
| `PUT /v1/agents/{agent_id}/knowledge-base` | any of `chunk_size` (200–1000, step 50, or 512), `top_k` (1–10), `fallback_message`, `hybrid_enabled`, `rerank_enabled`, `rag_enabled` | `200` as GET, plus `reindexing: true` when `chunk_size` changed (overlap is recomputed ≈12.5 %, every source of the agent is re-indexed). Unknown fields → 422. |
| `GET /v1/agents/{agent_id}/knowledge-base/status` | — | `{"files": 3, "urls": 2, "rag_enabled": true, "status": "ready", "label": "Knowledge base: 3 files, RAG on"}` |

## Sources (Phase 2)

| Method & path | Body | Response |
|---|---|---|
| `POST /v1/agents/{agent_id}/sources/files` | multipart, field `files` (1..20) | `202 [{source_id, status, file_name, duplicate}]`. PDF, DOCX, PPTX, TXT, MD, HTML only; type is sniffed from the bytes and must match the extension (`415`); max `MAX_UPLOAD_MB` (`413`); DOCX/PPTX with macros or zip-bomb shapes → `415`. The whole request is validated before anything is stored. Same bytes already in this agent → `duplicate: true` with the existing `source_id`. |
| `POST /v1/agents/{agent_id}/sources/urls` | `{url, crawl_depth? (0–3, 1), max_pages? (1–500, 50), recrawl_interval_hours?}` | `202 {source_id, status, url, duplicate}`. Private/loopback hosts → `422`. |
| `PUT /v1/agents/{agent_id}/sources/business-info` | `{company_name, hours, address, contact, faq: [{question, answer}]}` | `202`. One per agent; a new PUT replaces it and re-indexes. Indexed as a 1-page document named "Business info". |
| `GET /v1/agents/{agent_id}/sources` | — | `200 [{id, type, status, file_name, url, pages, chunks, language, error, …}]` — `status` ∈ queued, parsing, chunking, embedding, ready, error, deleting; `error` is human-readable. |
| `DELETE /v1/agents/{agent_id}/sources/{source_id}` | — | `202 {status: "deleting"}`; the worker deletes points, stored files and the row. Idempotent. |
| `POST /v1/agents/{agent_id}/sources/{source_id}/reindex` | — | `202`; `409` while deleting. |

A source id from another tenant or agent is always `404`. `503 service_unavailable` when the
job could not be queued (the source then shows the error and can be retried).

## Planned (spec section 7)
`/test`, `/answer`
(SSE), `/ws`, and the gRPC `RagService` ([`proto/beai/rag/v1/rag.proto`](../proto/beai/rag/v1/rag.proto))
are added in Phases 3–4 and documented here as they land.
