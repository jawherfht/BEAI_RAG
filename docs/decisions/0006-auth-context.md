# ADR 0006 — Auth context from the API Gateway

Status: accepted (Phase 1)

- **JWT** (`Authorization: Bearer`): verified with the gateway's public key (`JWT_PUBLIC_KEY`,
  RS256/ES256). HS256 with `JWT_SECRET` is allowed only outside `prod` (settings validation
  refuses it in prod). `exp` and the tenant claim (`JWT_TENANT_CLAIM`, default `tenant_id`)
  are required. Optional `agents` claim = the agents this caller may use.
- **API key** (`X-API-Key`): looked up by SHA-256 in `API_KEYS` (JSON from Vault/env), giving
  `tenant_id` and optional `agents`. Constant-time comparison.
- `agent_id` in the path → `TenantScope`. Not in the caller's `agents` list, or malformed →
  **404**, never 403 or 422. When the gateway sends no `agents` list, isolation still holds
  because every DB row and Qdrant point is looked up by (tenant_id, agent_id); an agent of
  another tenant simply has no knowledge base → 404 (Phase 2 endpoints).
- Request bodies are never read for tenant/agent (tested: `test_body_cannot_override_tenant`).
- gRPC (Phase 4): tenant/agent from metadata of an mTLS-authenticated caller.
