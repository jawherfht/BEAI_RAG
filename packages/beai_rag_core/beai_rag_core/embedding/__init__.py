"""Pluggable embedders: dense (TEI / vLLM / local), sparse BM25 (FastEmbed), tokenizer."""

from beai_rag_core.embedding.base import DenseEmbedder, SparseEncoder, SparseVector, TokenCounter
from beai_rag_core.embedding.factory import (
    build_dense_embedder,
    build_sparse_encoder,
    build_token_counter,
)

__all__ = [
    "DenseEmbedder",
    "SparseEncoder",
    "SparseVector",
    "TokenCounter",
    "build_dense_embedder",
    "build_sparse_encoder",
    "build_token_counter",
]
