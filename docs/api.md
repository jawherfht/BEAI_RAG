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
| `GET /readyz` | `200` or `503` `{"status": "ok"\|"unavailable", "checks": {"embedder"\|"qdrant"\|"postgres"\|"redis"\|"rabbitmq"\|"object_storage"\|"llm"[\|"reranker"]: {"ok": bool, "latency_ms": float, "error"?: str}}}` (`reranker` when `READINESS_CHECK_RERANKER=true`) |
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

## Answering (Phase 4)

Request body for `/test`, `/answer` and WebSocket messages (the tenant and agent come from auth):

```json
{"question": "What's your return policy?",
 "language": "en",
 "persona": {"agent_name": "Acme", "role": "store assistant", "instructions": "", "tone": "warm",
             "response_style": "concise", "boundaries": "only store topics"},
 "conversation_history": [{"role": "user", "text": "..."}, {"role": "assistant", "text": "..."}]}
```

| Method & path | Response |
|---|---|
| `POST /v1/agents/{agent_id}/test` | `200 {answer, spoken_text, sources: [{file_name, page, section, url, snippet, score}], confidence: high\|medium\|low, fallback, latency_ms: {embed, search, rerank, llm_ttft, llm_total, total[, llm_rate_limit_wait, cache]}, cache_hit, error}` |
| `POST /v1/agents/{agent_id}/answer` | `200 text/event-stream`: `event: token` `{text, spoken}` …, `event: sources` `{sources}`, `event: done` (same object as `/test`). Errors before streaming (404 no knowledge base / foreign agent) are normal JSON errors. |
| `WS /v1/agents/{agent_id}/ws` | Auth: `Authorization: Bearer`, `X-API-Key`, or `?access_token=`. Send the request JSON; receive `{"type": "token"\|"sources"\|"done"\|"error", ...}`. Several questions per connection. Close codes 4401 (credentials), 4404 (agent). |

`fallback: true` with `confidence: "low"` and no sources means the knowledge base does not answer
the question (the LLM is not called when retrieval is below the threshold). `error:
"llm_unavailable"` means the LLM could not be reached after retries; the fallback message is
returned.

## gRPC (Phase 4)

`proto/beai/rag/v1/rag.proto`, service `RagService` on `GRPC_PORT` (50051): `Retrieve`,
`Answer` (server stream: `token` chunks then one `final`), `GetKnowledgeBaseStatus`. Metadata
`x-beai-tenant-id` and `x-beai-agent-id` (UUIDs) are required (`UNAUTHENTICATED` otherwise);
an agent without a knowledge base in that tenant is `NOT_FOUND`. The server requires mTLS
(`GRPC_TLS_CERT`, `GRPC_TLS_KEY`, `GRPC_CLIENT_CA`); `GRPC_ALLOW_INSECURE=true` is dev only.
Regenerate code with `make proto`.

## Usage events

One message per answer on the durable queue `usage.events`:
`{"type": "rag.answer", "tenant_id", "agent_id", "tokens_in", "tokens_out", "rerank_used",
"fallback", "llm_model", "ts"}`.
