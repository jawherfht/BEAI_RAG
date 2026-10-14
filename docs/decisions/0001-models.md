# ADR 0001 — Models (embedder, sparse, re-ranker, LLM)

Status: **partially verified (Phase 1)** — full verification is a Phase 2/3/4 entry task.

## What Phase 1 depends on
Only the dense vector size of the `kb_chunks` collection.

| Item | Spec value | Found | Source |
|---|---|---|---|
| `microsoft/harrier-oss-v1-0.6b` dimension | 1024 | 1024, last-token pooling + L2 normalisation, 32,768-token max length | Azure AI model catalog entry; FuriosaAI model docs (secondary) |
| Query instruction | "as the model card requires" | Queries take a one-line task instruction (`Instruct: <task>\nQuery: <text>`); documents are encoded without instruction | secondary sources — **must be confirmed on the HF card** |
| Licence | MIT | MIT per aggregators — **not yet confirmed on the HF card** | — |

## Why not fully verified
The build container's network policy blocks `huggingface.co` (HTTP 403 from the egress proxy),
so the model card, `config.json` and licence file could not be read directly.

## To do before Phase 2 (embedding) starts
- Read the HF cards for: harrier-oss-v1-0.6b (+ revision sha), Qwen3-Embedding-0.6B (fallback),
  Qdrant/bm25 (FastEmbed), Qwen3-Reranker-0.6B, and the LLM (`Qwen3.8-27B` — exact repo id
  unknown; verify it exists and how to disable thinking).
- Check TEI support for harrier (architecture/pooling); else vLLM pooling or sentence-transformers.
- Record exact instruction strings, max lengths and licences here.

If harrier's dimension turns out different, only `EMBED_DIM` and a fresh collection are needed.
