# Phase 3 retrieval — KB #1 (hybrid+rerank, chunk 512, subset 20)

Questions: 20 answerable · sources: 5 · chunks: 33 · ingest 58 s

| Metric | Value | Target |
|---|---|---|
| Recall@4 (evidence in top 4) | **1.000** | ≥ 0.90 |
| Recall@1 | 0.950 | — |
| MRR@10 | **0.967** | ≥ 0.75 |
| Citation file+page correct (of recall@4 hits) | 20/20 | — |

Latency per query (ms), this machine:

| Stage | p50 | p95 |
|---|---|---|
| embed | 795.1 | 1589.7 |
| search | 41.1 | 63.1 |
| rerank | 35845.4 | 40243.3 |
| retrieval_total | 36644.7 | 40960.6 |
