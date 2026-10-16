# ADR 0008 — Retrieval (Phase 3)

Status: accepted (Phase 3)

## Hybrid search in one call
`QdrantStore.hybrid_search` issues a single Query API request: two prefetches (dense, limit 50,
int8 quantised with rescoring and 2× oversampling; BM25 sparse, limit 50), both carrying the
mandatory `tenant_id AND agent_id` filter, fused with RRF. `limit = top_k`, or 50 when the
agent enabled re-ranking. `hybrid_enabled = false` → dense only.

## BM25 IDF scoped to the agent
Qdrant ≥ 1.19 can compute IDF over a filtered corpus. We pass `IdfCorpusParams(corpus=<tenant+agent
filter>)`: keyword weights come only from the agent's own documents. This keeps ranking
independent of other tenants (no cross-tenant statistics) and matches the agent's vocabulary.
Measured cost: search p95 29 ms on KB #1 (CPU dev machine) — inside budget.

## Scores
- RRF scores are rank-based, so the grounding check uses the **exact dense cosine** of each final
  chunk (vectors are unit-normalised; the hit's dense vector is returned and dotted with the
  query). `top_score` = best cosine, or the re-ranker score when re-ranking ran.
- Re-ranker scores (P("yes") in [0, 1]) live on another scale and have their own thresholds
  (`RERANK_SCORE_THRESHOLD`, `RERANK_CONF_MID`, `RERANK_CONF_HIGH`). All values are placeholders
  until the Phase 6 calibration. A per-KB `score_threshold` overrides the dense threshold.

## Re-ranker serving
TEI 1.8.3 cannot serve Qwen3-Reranker (a causal LM scored by yes/no logits; TEI expects a
classifier or a pooling config). Providers behind one `Reranker` interface:
- `local`: `services/embed-server` `POST /rerank`, implementing the model card verbatim
  (system prefix, `<Instruct>/<Query>/<Document>`, softmax over the "no"/"yes" logits).
- `vllm`: vLLM's score task for Qwen3-Reranker (production, GPU pool); the client formats query
  and documents with the card template.
Re-ranking is skipped when fewer than 10 candidates come back (`RERANK_MIN_CANDIDATES`).

## Cache
`sha256(tenant | agent | kb_version | normalised question)` with a kind prefix
(`beai:rag:retrieval:` now, `beai:rag:answer:` in Phase 4), TTL 24 h. Normalisation: NFKC,
casefold, collapse whitespace, strip trailing punctuation (Latin, CJK, Arabic `؟`). Keys are
hashed, so no question text or tenant id is stored in key names.

## Latency (Phase 3 acceptance: retrieval p95 ≤ 60 ms with GPU embeddings)
Measured on the 4-vCPU dev machine: Qdrant search p50 20 ms / p95 29 ms; query embedding on CPU
p50 0.7 s / p95 1.7 s. The embedding part of the budget (≤ 20 ms) needs the GPU embedding pool
and must be confirmed there before production, as for the ingestion benchmark.
