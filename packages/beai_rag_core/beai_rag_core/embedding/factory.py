"""Build embedders from settings. Swapping to a fallback model is a config change."""

from __future__ import annotations

from beai_rag_core.embedding.base import DenseEmbedder, SparseEncoder, TokenCounter
from beai_rag_core.embedding.http_dense import OpenAIEmbedder, TEIEmbedder
from beai_rag_core.embedding.sparse import FastEmbedBM25
from beai_rag_core.embedding.tokenizer import HFTokenCounter
from beai_rag_core.settings import CoreSettings


def build_dense_embedder(settings: CoreSettings) -> DenseEmbedder:
    if settings.embed_provider == "vllm":
        return OpenAIEmbedder(
            settings.embed_url,
            settings.embed_model,
            settings.embed_dim,
            settings.embed_query_template,
            batch_size=settings.embed_batch_size,
            timeout_s=settings.embed_timeout_s,
            api_key=settings.llm_key(),
        )
    # "tei" (GPU) and "local" (a CPU embedding service, e.g. the TEI CPU image) share the
    # TEI /embed contract, so the code path is identical.
    return TEIEmbedder(
        settings.embed_url,
        settings.embed_model,
        settings.embed_dim,
        settings.embed_query_template,
        batch_size=settings.embed_batch_size,
        timeout_s=settings.embed_timeout_s,
    )


def build_sparse_encoder(settings: CoreSettings) -> SparseEncoder:
    return FastEmbedBM25(settings.sparse_model, cache_dir=settings.model_cache_dir)


def build_token_counter(settings: CoreSettings) -> TokenCounter:
    return HFTokenCounter(
        settings.tokenizer_model or settings.embed_model, revision=settings.embed_model_revision
    )


def embed_model_tag(settings: CoreSettings) -> str:
    """Value stored in each point's ``embed_model`` payload, e.g. ``harrier-oss-v1-0.6b@main``."""
    return f"{settings.embed_model.rsplit('/', 1)[-1]}@{settings.embed_model_revision}"
