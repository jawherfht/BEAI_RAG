"""Dense embedders served over HTTP: Text Embeddings Inference and OpenAI-compatible (vLLM)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import httpx

from beai_rag_core.embedding.base import EmbeddingDimensionError


class _HttpEmbedder:
    def __init__(
        self,
        base_url: str,
        model: str,
        dim: int,
        query_template: str,
        *,
        batch_size: int = 32,
        timeout_s: float = 60.0,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if "{text}" not in query_template:
            raise ValueError("EMBED_QUERY_TEMPLATE must contain {text}")
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout_s, headers=headers
        )
        self._model = model
        self._dim = dim
        self._template = query_template
        self._batch = batch_size

    @property
    def model_id(self) -> str:
        return self._model

    @property
    def dim(self) -> int:
        return self._dim

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed_batched(list(texts))

    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._embed_batched([self._template.replace("{text}", t) for t in texts])

    async def _embed_batched(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self._batch):
            vectors = await self._embed(texts[i : i + self._batch])
            for v in vectors:
                if len(v) != self._dim:
                    raise EmbeddingDimensionError(
                        f"{self._model} returned {len(v)} dims, EMBED_DIM is {self._dim}"
                    )
            out.extend(vectors)
        return out

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    async def ping(self) -> None:
        await self._embed(["ping"])

    async def close(self) -> None:
        await self._client.aclose()


class TEIEmbedder(_HttpEmbedder):
    """Hugging Face Text Embeddings Inference: POST /embed."""

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        resp = await self._client.post(
            "/embed", json={"inputs": texts, "normalize": True, "truncate": True}
        )
        resp.raise_for_status()
        data: list[list[float]] = resp.json()
        return data


class OpenAIEmbedder(_HttpEmbedder):
    """OpenAI-compatible /embeddings (vLLM pooling mode). Vectors are L2-normalised here."""

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        resp = await self._client.post("/embeddings", json={"model": self._model, "input": texts})
        resp.raise_for_status()
        items: list[dict[str, Any]] = sorted(resp.json()["data"], key=lambda d: d["index"])
        return [_normalise(item["embedding"]) for item in items]


def _normalise(v: list[float]) -> list[float]:
    norm = sum(x * x for x in v) ** 0.5
    return [x / norm for x in v] if norm else v
