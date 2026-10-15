# ADR 0001 — Models (embedder, sparse, re-ranker, LLM)

Status: **partially verified** — Hugging Face is still blocked from the build environment (Phase 2).

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

## How the code depends on these values (Phase 2)
- `EMBED_QUERY_TEMPLATE` (default `Instruct: Given a question, retrieve passages from the
  knowledge base that answer it\nQuery: {text}`) is applied to queries only; documents are
  embedded raw. To be replaced by the exact wording on the model card.
- Chunk sizes are counted with the embed model's `tokenizer.json` (`tokenizers` library,
  `TOKENIZER_MODEL` overrides).
- Each point stores `embed_model = <repo-name>@<EMBED_MODEL_REVISION>`.
- `EMBED_PROVIDER=tei` (GPU or the TEI CPU image) or `vllm` (OpenAI `/embeddings`); swapping to
  the fallback (`Qwen/Qwen3-Embedding-0.6B`) is a config change plus a re-index.
- Docling downloads its layout/table/OCR models from Hugging Face on first use, or reads them from
  `DOCLING_ARTIFACTS_PATH`; FastEmbed downloads `Qdrant/bm25`.

## To do as soon as Hugging Face is reachable
- Read the HF cards for: harrier-oss-v1-0.6b (+ revision sha), Qwen3-Embedding-0.6B (fallback),
  Qdrant/bm25 (FastEmbed), Qwen3-Reranker-0.6B, and the LLM (`Qwen3.8-27B` — exact repo id
  unknown; verify it exists and how to disable thinking).
- Check TEI support for harrier (architecture/pooling); else vLLM pooling or sentence-transformers.
- Record exact instruction strings, max lengths and licences here.

If harrier's dimension turns out different, only `EMBED_DIM` and a fresh collection are needed.
