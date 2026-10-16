"""Test doubles for the model servers. NOT used for acceptance runs.

``HashingEmbedder`` maps words into a fixed-size vector (feature hashing), so texts that share
words are similar. It lets pipeline/integration tests run without the real embedding model.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import AsyncIterator, Sequence

from beai_rag_core.embedding.base import SparseVector

_WORD = re.compile(r"\w+", re.UNICODE)


def _bucket(word: str, dim: int) -> int:
    return int.from_bytes(hashlib.blake2b(word.encode(), digest_size=8).digest(), "big") % dim


class HashingEmbedder:
    def __init__(self, dim: int = 1024) -> None:
        self._dim = dim
        self.document_calls = 0
        self.query_calls = 0

    @property
    def model_id(self) -> str:
        return "test/hashing-embedder"

    @property
    def dim(self) -> int:
        return self._dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self._dim
        for w in _WORD.findall(text.lower()):
            v[_bucket(w, self._dim)] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.document_calls += 1
        return [self._vec(t) for t in texts]

    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        self.query_calls += 1
        return [self._vec(t) for t in texts]

    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None


class HashingSparse:
    @property
    def model_id(self) -> str:
        return "test/hashing-bm25"

    def _vec(self, text: str) -> SparseVector:
        counts: dict[int, float] = {}
        for w in _WORD.findall(text.lower()):
            b = _bucket(w, 2**20)
            counts[b] = counts.get(b, 0.0) + 1.0
        items = sorted(counts.items())
        return SparseVector([i for i, _ in items], [v for _, v in items])

    async def encode_documents(self, texts: Sequence[str]) -> list[SparseVector]:
        return [self._vec(t) for t in texts]

    async def encode_queries(self, texts: Sequence[str]) -> list[SparseVector]:
        return [self._vec(t) for t in texts]


class ScriptedLLM:
    """OpenAI-compatible LLM double: answers from a function of the prompt, streams words."""

    def __init__(self, reply=None, *, fail: Exception | None = None) -> None:  # type: ignore[no-untyped-def]
        self._reply = reply or (
            lambda messages: (
                "Returns are accepted within 30 days, unworn, with receipt [1] — see Section 4."
            )
        )
        self._fail = fail
        self.calls: list[list[dict[str, str]]] = []

    def stream(self, messages, *, max_tokens: int, temperature: float):  # type: ignore[no-untyped-def]
        from app.generation.llm import LLMEvent, Usage

        async def gen() -> AsyncIterator[LLMEvent]:
            self.calls.append(list(messages))
            if self._fail is not None:
                raise self._fail
            text = self._reply(messages)
            for word in re.findall(r"\S+\s*", text):
                yield LLMEvent(token=word)
            yield LLMEvent(usage=Usage(prompt_tokens=321, completion_tokens=len(text.split())))

        return gen()

    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None
