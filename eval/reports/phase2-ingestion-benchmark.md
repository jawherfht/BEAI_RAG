# Phase 2 — ingestion benchmark (upload → ready)

Date: 2026-10-15 · Machine: cloud dev container, **4 vCPU, no GPU**, 15 GB RAM ·
Docling 2.139 (CPU torch) · embedder `microsoft/harrier-oss-v1-0.6b@f9b9dc8` via
`services/embed-server` on the same 4 vCPU · BM25 `Qdrant/bm25` (FastEmbed) · chunk size 512.

Target (spec section 12): **50-page PDF, upload → ready ≤ 2 min.**

> **Decision (product owner, 2026-10-15):** the target is accepted as met **on the planned GPU
> embedding pool**; no extra CPU-only scaling is built for now. **It must be confirmed with a
> real GPU benchmark (TEI on the GPU pool, production worker size) before production.**
> Re-run: `make phase2-check PDF=eval/datasets/bench/handbook-50p.pdf` with `EMBED_URL` pointing
> at the GPU TEI, and record the result here.

## Results

| Document | Pages | Chunks | Parse (Docling) | Chunk | Embed | Upsert | **Total** | Target |
|---|---|---|---|---|---|---|---|---|
| `kb1_retail/returns-policy.pdf` (acceptance) | 2 | 7 | — | — | — | — | **36 s** (incl. first BM25/tokenizer download) | ✅ |
| `bench/handbook-50p.pdf` | 50 | 60 | 119.9 s | 0.7 s | **276.6 s** | 0.1 s | **397.4 s** | ❌ 3.3× over |

Docling-only measurements on the same machine (models already loaded):

| Docling setting | 50 pages |
|---|---|
| layout + tables (ACCURATE), OCR on | 98–109 s (PyPI torch) · 106–118 s (CPU-only torch) |
| layout + tables, OCR off | 97–100 s |
| layout + tables (FAST) | 91 s |
| layout only (no table structure) | 65 s |

CPU embedding (harrier 0.6B, idle machine): **≈ 4.6 s per 500-token chunk**, independent of
batch size.

## Why it misses, and what would meet it

1. **Embedding on CPU is ~70 % of the time.** The spec puts the embedder on the GPU pool
   (TEI). On a GPU, 60 chunks of 512 tokens take a few seconds, which would bring this run to
   ≈ 125 s with Docling as measured here.
2. **Docling on 4 vCPU takes ~100 s per 50 pages** (≈ 2 s/page), plus ~15 s model loading in
   a fresh process. This is the CPU-only-torch decision's cost. On an 8–16 vCPU worker node the
   layout model scales roughly with cores (not measured here).

Proposed fixes, in order of effect:
- Embed on the GPU pool as the spec says (TEI or vLLM). Expected total ≈ 2 min on 4 vCPU.
- Give ingestion workers more vCPU (8+), and keep Docling models loaded (the worker does;
  the first job after start pays the load).
- Optional: TableFormer FAST mode (−7 %), and/or parallel page batches across workers for
  very large PDFs.

TEI on CPU was tested afterwards (`cpu-1.8.3`): same vectors as sentence-transformers and the
same CPU speed (≈ 5.5 s per 500-token chunk), so the CPU numbers above hold for TEI too.
Docling re-measured with CPU-only torch (`2.14.1+cpu`, 2026-10-16, fresh container): 50-page
parse **106–118 s** (2 runs) vs 98–109 s with the PyPI torch build — within run-to-run noise to
≈ 8 % slower. Conclusions unchanged.
