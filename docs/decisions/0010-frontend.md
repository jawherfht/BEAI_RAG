# ADR 0010 — Screen B frontend (Phase 5)

Status: accepted (Phase 5)

- **Stack**: Next.js 16.3.8 (App Router), React 19.3, TypeScript 5.9 strict
  (`noUncheckedIndexedAccess`), Tailwind 4.3, ESLint 9 flat config (`eslint-config-next`).
  TypeScript 7 (native compiler) was not used: Next's type-check integration targets TS 5.
- **Pages**: `/agents/[agentId]/knowledge-base` (screen B) and a minimal
  `/agents/[agentId]/persona` stand-in for screen 4 showing `<KnowledgeBaseStatusChip>`.
  `?agentName=` sets the subtitle; `?lang=fr` switches language.
- **i18n**: every UI string lives in `src/i18n/en.json` / `fr.json` (same keys, checked);
  server-safe helpers in `i18n/core.ts`, React provider/hook in `i18n/index.tsx`.
- **API access (BFF)**: the browser only calls `/api/rag/...`, a Next.js route handler that
  forwards an allow-listed set of paths (`/v1/agents/{uuid}/knowledge-base|sources|test|answer`)
  to rag-api, streaming request and response bodies (multipart uploads, SSE). Auth: a user token
  forwarded by the platform wins; in local dev (`DEV_AUTH=true`) the handler signs a 5-minute
  gateway-style JWT for `DEV_TENANT_ID` (jose). No secret reaches the browser.
- **Behaviour**: sources poll every 2 s while any is processing; settings auto-save after
  600 ms of inactivity (a chunk-size change starts the agent-wide re-index and shows
  "Re-indexing…"); Save & Continue flushes pending settings and opens screen 4. The test panel
  streams `/answer` (fetch + SSE parser, since EventSource cannot POST), strips `[n]` markers
  live, and shows source chips (`file p.N`, click for the snippet), a confidence badge and a
  latency line.
- **Chunk-size slider**: an index over the allowed values (200–1000 step 50, plus the 512
  default — ADR 0004), so the default is reachable and shown exactly.
- **Accessibility**: labelled controls, `role="switch"` toggles, live regions for status and
  answers, native `<dialog>` for business info, visible focus, AA-contrast colours; layout
  collapses to one column on phones (screenshots in `docs/screens/`).
- **Licences**: `npm run licenses` gate (MIT/Apache/permissive). Exceptions: optional
  `sharp`/libvips (LGPL) — image optimisation disabled and stripped from the Docker image;
  `caniuse-lite` (CC-BY-4.0 data, attribution in `THIRD_PARTY_NOTICES.md`).
- **E2E**: Playwright against the real stack (`make e2e`): upload 3 files → Ready, move the
  slider → re-index → Ready, ask the wireframe question → answer + `returns-policy.pdf p.2` +
  confidence high, Save & Continue → chip "Knowledge base: 3 files, RAG on"; plus a French /
  fallback test. Runs in CI once a staging stack with models exists (Phase 7).
