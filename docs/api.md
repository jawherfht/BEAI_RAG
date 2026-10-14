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
Codes in use: `unauthorized` (401), `not_found` (404), `validation_error` (422),
`conflict` (409), `internal_error` (500).

## Health (Phase 1)

| Method & path | Response |
|---|---|
| `GET /healthz` | `200 {"status": "ok"}` — process is alive |
| `GET /readyz` | `200` or `503` `{"status": "ok"\|"unavailable", "checks": {"qdrant"\|"postgres"\|"redis"\|"rabbitmq"\|"object_storage": {"ok": bool, "latency_ms": float, "error"?: str}}}` |
| `GET /metrics` | Prometheus text format |

## Planned (spec section 7)
Knowledge base settings/status, sources (files, URLs, business info), `/test`, `/answer`
(SSE), `/ws`, and the gRPC `RagService` ([`proto/beai/rag/v1/rag.proto`](../proto/beai/rag/v1/rag.proto))
are added in Phases 2–4 and documented here as they land.
