"""Embedding interfaces. Implementations are chosen by config (EMBED_PROVIDER, models)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SparseVector:
    indices: list[int]
    values: list[float]


class DenseEmbedder(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def dim(self) -> int: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Document mode: no instruction prefix."""
        ...

    async def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        """Query mode: applies the instruction/prefix the model card requires."""
        ...

    async def ping(self) -> None: ...

    async def close(self) -> None: ...


class SparseEncoder(Protocol):
    @property
    def model_id(self) -> str: ...

    async def encode_documents(self, texts: Sequence[str]) -> list[SparseVector]: ...

    async def encode_queries(self, texts: Sequence[str]) -> list[SparseVector]: ...


class TokenCounter(Protocol):
    def count(self, text: str) -> int: ...

    def split_to_budget(self, text: str, budget: int) -> list[str]:
        """Split text into pieces of at most ``budget`` tokens (last-resort splitting)."""
        ...


class EmbeddingDimensionError(RuntimeError):
    pass
