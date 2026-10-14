# CLAUDE.md

> Copied from section 0 of `BEAI_RAG_BUILD_SPEC.md`. The spec is the source of truth.

You are building the **Knowledge Base & RAG module** of BEAI™ Studio, a platform for AI avatars and **live interactive agents** that listen and answer in real time. This module makes a live avatar answer **only from the customer's own documents** (PDFs, DOCX, websites), **with a citation (file + page)** and a **confidence level**, fast enough for a spoken conversation.

Working rules:
1. **Follow this spec exactly.** If something is ambiguous or impossible (for example, a model is not supported by a library), stop, explain the problem, propose 1–2 options, and ask. Do not silently change the stack.
2. **Work in phases (section 15).** Never start a phase before the previous phase's acceptance checks pass.
3. **Verify, don't assume:** before using any model or library, check its current docs or model card (supported versions, required prefixes and instructions, licence). Record what you found in `docs/decisions/` as a short ADR.
4. **Licence rule:** only MIT or Apache-2.0 components in production. Never add CC-BY-NC, Gemma Terms, or Llama-licensed models.
5. **Security rule:** the tenant and agent scope come **only** from the authenticated context, never from the request body. Every vector query carries a `tenant_id` + `agent_id` filter, added inside the retrieval layer.
6. **Latency rule:** nothing slow runs on the live query path. Parsing, crawling, chunking and embedding of documents are always asynchronous.
7. Python code: typed (`mypy --strict` passes), formatted with `ruff format`, linted with `ruff`, tested with `pytest`. TypeScript: strict mode, ESLint.
8. No secrets in code. Read them from environment variables. Production secrets come from Vault, as in the platform's Secrets layer.
9. Keep `README.md`, `docs/architecture.md` and `docs/api.md` up to date at the end of every phase.

## Repo conventions (added during the build)
- Python workspace managed by `uv` (root `pyproject.toml`, members under `packages/` and `services/`). Python 3.12.
- `make lint` / `make typecheck` / `make test` must pass before a phase is reported done.
- The only module allowed to call the Qdrant client directly is `packages/beai_rag_core/beai_rag_core/qdrant_store.py` (re-exported as `app.retrieval.qdrant_store`). `tests/unit/test_no_raw_qdrant_calls.py` enforces this.
- ADRs live in `docs/decisions/NNNN-title.md`.
