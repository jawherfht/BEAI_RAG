# ADR 0001 — Models (embedder, sparse, re-ranker, LLM)

Status: **verified on the Hugging Face cards (2026-10-15)**. Pinned revisions below.

| Role | Repo id @ revision | Licence | Facts from the card / config | Serving |
|---|---|---|---|---|
| Dense embedder (main) | `microsoft/harrier-oss-v1-0.6b` @ `f9b9dc8d367d443f2479d27aa5d8d2850c0774ee` | MIT | `Qwen3Model`, hidden 1024, **1024-dim**, **last-token pooling** + L2 normalise, 32,768 max tokens, multilingual (~94 languages listed). Queries take a prompt; documents none. | TEI (Qwen3 architecture, pooling read from `1_Pooling`), or the in-repo sentence-transformers server (`services/embed-server`, TEI `/embed` contract) |
| Dense embedder (fallback) | `Qwen/Qwen3-Embedding-0.6B` @ `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3` | Apache-2.0 | 1024-dim, last-token pooling, query prompt `Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery:` (no space at the end), documents none | same |
| Sparse | `Qdrant/bm25` @ `22b8d2af71a76161e18dd432d2cee0eefa66e412` | Apache-2.0 | stop-word lists + Snowball stemmer per language; FastEmbed computes TF; Qdrant applies IDF (`modifier: idf`) | FastEmbed in-process |
| Re-ranker | `Qwen/Qwen3-Reranker-0.6B` @ `e61197ed45024b0ed8a2d74b80b4d909f1255473` | Apache-2.0 | yes/no logit scoring with a fixed system prefix and `<Instruct>/<Query>/<Document>` user turn, max length 8192 | Phase 3 |
| LLM | `Qwen/Qwen3.8-27B` @ `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0` (also `-FP8`) | Apache-2.0 | vision-language, **thinking on by default**; disable per request with `chat_template_kwargs: {"enable_thinking": false}` (vLLM/SGLang). Card's non-thinking sampling: temperature 0.7, top_p 0.8 — the spec fixes 0.2 for grounding. | vLLM, Phase 4 |

## Query prompt
`EMBED_QUERY_TEMPLATE` defaults to the harrier card's `web_search_query` prompt, verbatim:
`Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: {text}`.
For the fallback model, set it to the Qwen3-Embedding wording (`...\nQuery:{text}`, no space).

## How the code depends on these values
- Documents are embedded raw; queries get the template (`beai_rag_core.embedding.http_dense`).
- Chunk sizes are counted with the embed model's `tokenizer.json` (`tokenizers`, pinned revision).
- Each point stores `embed_model = <repo-name>@<EMBED_MODEL_REVISION>`.
- `EMBED_PROVIDER=tei|local` (TEI `/embed` contract) or `vllm` (OpenAI `/embeddings`). Swapping to
  the fallback is a config change plus a re-index.
- Docling downloads its layout/table models (and EasyOCR models when OCR is used) from Hugging
  Face on first use, or reads them from `DOCLING_ARTIFACTS_PATH`.

## TEI support
TEI supports the Qwen3 architecture with last-token pooling (the same as Qwen3-Embedding).
Not exercised here: the build environment cannot pull images from ghcr.io (blob host blocked),
so the acceptance run uses `services/embed-server` (sentence-transformers, identical model and
`/embed` contract). TEI remains the production choice; verify with `docker compose --profile
gpu up tei` on the GPU pool.
