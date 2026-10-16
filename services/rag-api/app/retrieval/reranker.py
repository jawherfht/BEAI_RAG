"""Re-ranker clients for Qwen3-Reranker-0.6B (spec section 6, step 4).

Qwen3-Reranker is a causal LM that scores relevance as P("yes") for a fixed prompt (see the
model card / ADR 0001). TEI 1.8 cannot serve it, so two providers exist behind one interface:

- ``local``: our embed-server's ``POST /rerank`` (TEI contract: ``{query, texts}`` ->
  ``[{index, score}]``); the server applies the card's prompt template.
- ``vllm``: vLLM's score task (``POST /rerank``, Jina/Cohere contract) for Qwen3-Reranker; the
  client formats query and documents with the card's template, as vLLM's docs require.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

import httpx

DEFAULT_INSTRUCTION = "Given a web search query, retrieve relevant passages that answer the query"

# Prompt pieces from the Qwen3-Reranker-0.6B card (used by the vLLM provider).
CARD_PREFIX = (
    "<|im_start|>system\nJudge whether the Document meets the requirements based on the Query "
    'and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n'
    "<|im_start|>user\n"
)
CARD_SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"


class Reranker(Protocol):
    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        """Relevance score in [0, 1] for each document, in input order."""
        ...

    async def ping(self) -> None: ...

    async def close(self) -> None: ...


class LocalReranker:
    def __init__(
        self, base_url: str, *, timeout_s: float = 30.0, client: httpx.AsyncClient | None = None
    ) -> None:
        self._client = client or httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout_s)

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []
        resp = await self._client.post("/rerank", json={"query": query, "texts": list(documents)})
        resp.raise_for_status()
        scores = [0.0] * len(documents)
        for item in resp.json():
            scores[int(item["index"])] = float(item["score"])
        return scores

    async def ping(self) -> None:
        await self.rerank("ping", ["ping"])

    async def close(self) -> None:
        await self._client.aclose()


class VllmReranker:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        instruction: str = DEFAULT_INSTRUCTION,
        api_key: str | None = None,
        timeout_s: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=timeout_s, headers=headers
        )
        self._model = model
        self._instruction = instruction

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []
        q = f"{CARD_PREFIX}<Instruct>: {self._instruction}\n<Query>: {query}\n"
        docs = [f"<Document>: {d}{CARD_SUFFIX}" for d in documents]
        resp = await self._client.post(
            "/rerank", json={"model": self._model, "query": q, "documents": docs}
        )
        resp.raise_for_status()
        scores = [0.0] * len(documents)
        for item in resp.json()["results"]:
            scores[int(item["index"])] = float(item["relevance_score"])
        return scores

    async def ping(self) -> None:
        await self.rerank("ping", ["ping"])

    async def close(self) -> None:
        await self._client.aclose()
