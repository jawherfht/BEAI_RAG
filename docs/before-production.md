# Before production — items to confirm on the GPU pool

Everything below works and is tested on the dev stack (4 vCPU, no GPU; LLM on Groq). These items
can only be confirmed with production hardware and must be signed off before go-live.

| # | Item | Target (spec) | Dev result | How to confirm |
|---|---|---|---|---|
| 1 | Ingestion: 50-page PDF upload → ready | ≤ 2 min (§12) | 397 s on CPU (Docling ~106–118 s, CPU embedding 277 s) — [report](../eval/reports/phase2-ingestion-benchmark.md) | `make phase2-check PDF=eval/datasets/bench/handbook-50p.pdf` with `EMBED_URL` → TEI on GPU, production worker size |
| 2 | Query embedding latency | ≤ 20 ms p95 (§1.4) | 0.7 s p50 / 1.7 s p95 on CPU | `make eval-retrieval` against GPU TEI |
| 3 | Retrieval (embed + search + checks) | ≤ 60 ms p95 (§1.4, §12) | search alone 20 ms p50 / 29 ms p95 | `make eval-retrieval`, read `retrieval_total` p95 |
| 4 | Re-ranker latency (when enabled) | fits the < 500 ms end-to-end budget | ~36 s/query on CPU (33 passages) | vLLM score task for Qwen3-Reranker-0.6B on GPU; `make eval-retrieval ARGS=--rerank` |
| 5 | LLM TTFT (Qwen3.8-27B, thinking off) | ≤ 300 ms p50 / ≤ 500 ms p95 (§1.4, §12) | Groq-hosted: p50 291 ms / p95 501 ms (not our hardware) | `make phase4-check` with `LLM_BASE_URL` → vLLM on the GPU pool, `LLM_THINKING_SWITCH=chat_template_kwargs` |
| 6 | TEI serving harrier on GPU | vectors = sentence-transformers | verified on TEI **CPU** image 1.8.3 (cosine 0.998–1.002) | `docker compose --profile gpu up tei`; repeat the vector comparison (ADR 0001) |
| 7 | vLLM serves Qwen3.8-27B with `chat_template_kwargs.enable_thinking=false` | no reasoning tokens, OpenAI-compatible stream | flag verified on the model card; dev used Groq's `reasoning_effort=none` | one `/test` call against vLLM; check no `<think>` / reasoning output |
| 8 | Threshold calibration | correct fallback ≥ 0.90, false fallback ≤ 0.05 (§12) | preliminary on KB #1 only (Phase 4); full calibration in Phase 6 | `make calibrate` / Phase 6 eval |
| 9 | Load test | 50 concurrent sessions, retrieval p95 ≤ 60 ms (§13) | not run yet (Phase 7) | k6 against the GPU deployment |
| 10 | Separate GPU node pool from avatar rendering | (§14) | — | Helm values / taints (Phase 7) |

Production switch (configuration only, no code change):

```
LLM_BASE_URL=http://vllm:8000/v1
LLM_MODEL=Qwen/Qwen3.8-27B
LLM_THINKING_SWITCH=chat_template_kwargs
EMBED_PROVIDER=tei            EMBED_URL=http://tei:80
RERANK_PROVIDER=vllm          RERANK_URL=http://reranker:8000/v1
GRPC_TLS_CERT / GRPC_TLS_KEY / GRPC_CLIENT_CA   (mTLS; never GRPC_ALLOW_INSECURE)
JWT_ALGORITHMS=RS256          JWT_PUBLIC_KEY=<gateway key>
```
