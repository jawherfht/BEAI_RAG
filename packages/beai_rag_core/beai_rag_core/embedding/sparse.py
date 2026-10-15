"""BM25 sparse vectors via FastEmbed (``Qdrant/bm25``); Qdrant applies IDF (modifier: idf)."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Sequence
from typing import Any

from beai_rag_core.embedding.base import SparseVector


class FastEmbedBM25:
    def __init__(self, model_name: str = "Qdrant/bm25", cache_dir: str | None = None) -> None:
        self._model_name = model_name
        self._cache_dir = cache_dir
        self._model: Any = None
        self._lock = threading.Lock()

    @property
    def model_id(self) -> str:
        return self._model_name

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                from fastembed import SparseTextEmbedding  # heavy import, loaded on first use

                self._model = SparseTextEmbedding(
                    model_name=self._model_name, cache_dir=self._cache_dir
                )
            return self._model

    def warm_up(self) -> None:
        self._load()

    async def encode_documents(self, texts: Sequence[str]) -> list[SparseVector]:
        return await asyncio.to_thread(self._encode, list(texts), False)

    async def encode_queries(self, texts: Sequence[str]) -> list[SparseVector]:
        return await asyncio.to_thread(self._encode, list(texts), True)

    def _encode(self, texts: list[str], query: bool) -> list[SparseVector]:
        model = self._load()
        embeddings = model.query_embed(texts) if query else model.embed(texts)
        return [
            SparseVector(indices=e.indices.tolist(), values=e.values.tolist()) for e in embeddings
        ]
