# Phase 3 retrieval — KB #1 (hybrid, chunk 512)

Questions: 100 answerable · sources: 5 · chunks: 33 · ingest 144 s

| Metric | Value | Target |
|---|---|---|
| Recall@4 (evidence in top 4) | **0.980** | ≥ 0.90 |
| Recall@1 | 0.920 | — |
| MRR@10 | **0.948** | ≥ 0.75 |
| Citation file+page correct (of recall@4 hits) | 98/98 | — |

Latency per query (ms), this machine:

| Stage | p50 | p95 |
|---|---|---|
| embed | 689.3 | 1684.2 |
| search | 19.9 | 29.1 |
| rerank | 0.0 | 0.0 |
| retrieval_total | 710.6 | 1704.5 |

Misses (evidence not in top 4):

- `kb1-a018` Will I get the delivery fee back if I return only one item? → rank 6; top-1 from returns-policy.pdf: "Report damaged or wrong items within 48 hours of delivery with a photo. Damaged …"
- `kb1-a041` How can I choose another delivery day? → rank 10; top-1 from shipping-guide.pdf: "After a missed delivery, the carrier tries again the next business day and then …"
