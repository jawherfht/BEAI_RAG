"""Live retrieval path (spec section 6, steps 2-6): embed -> hybrid search -> rerank -> grounding.

Nothing slow runs here: one query embedding, one Qdrant Query API call, and (only if the agent
enabled it and there are >= 10 candidates) one re-ranker call. The tenant + agent filter is
applied inside ``QdrantStore`` from the ``TenantScope``; this module cannot bypass it.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from app.retrieval.confidence import Thresholds
from app.retrieval.reranker import Reranker
from beai_rag_core.embedding.base import DenseEmbedder, SparseEncoder
from beai_rag_core.enums import Confidence
from beai_rag_core.qdrant_store import QdrantStore, ScoredChunk
from beai_rag_core.tenancy import TenantScope

SNIPPET_CHARS = 200
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RetrievalSettings:
    """Per-agent settings, read from the knowledge_bases row."""

    top_k: int = 4
    hybrid_enabled: bool = True
    rerank_enabled: bool = False


@dataclass(slots=True)
class RetrievedChunk:
    source_id: str
    file_name: str | None
    page: int | None
    page_end: int | None
    section: str | None
    url: str | None
    title: str | None
    text: str
    score: float  # dense cosine, or the re-ranker score when re-ranking ran
    dense_score: float
    rerank_score: float | None = None

    @property
    def snippet(self) -> str:
        text = " ".join(self.text.split())
        return text if len(text) <= SNIPPET_CHARS else text[: SNIPPET_CHARS - 1].rstrip() + "…"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RetrievedChunk:
        return cls(**data)


@dataclass(slots=True)
class RetrievalResult:
    chunks: list[RetrievedChunk]
    top_score: float | None
    confidence: Confidence
    fallback: bool
    reranked: bool
    latency_ms: dict[str, float] = field(default_factory=dict)
    # Ranked top-k before the grounding threshold (evaluation and logging only; not cached).
    candidates: list[RetrievedChunk] = field(default_factory=list)
    rerank_error: str | None = None
    rerank_checked: bool = False  # the re-ranker scored the final chunks as the grounding gate

    def to_dict(self) -> dict[str, Any]:
        return {
            "chunks": [c.to_dict() for c in self.chunks],
            "top_score": self.top_score,
            "confidence": self.confidence.value,
            "fallback": self.fallback,
            "reranked": self.reranked,
            "rerank_checked": self.rerank_checked,
            "latency_ms": self.latency_ms,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RetrievalResult:
        return cls(
            chunks=[RetrievedChunk.from_dict(c) for c in data["chunks"]],
            top_score=data["top_score"],
            confidence=Confidence(data["confidence"]),
            fallback=data["fallback"],
            reranked=data["reranked"],
            latency_ms=dict(data.get("latency_ms") or {}),
            rerank_checked=bool(data.get("rerank_checked", False)),
        )


class Retriever:
    def __init__(
        self,
        *,
        store: QdrantStore,
        dense: DenseEmbedder,
        sparse: SparseEncoder,
        reranker: Reranker | None,
        dense_thresholds: Thresholds,
        rerank_thresholds: Thresholds,
        prefetch_limit: int = 50,
        rerank_candidates: int = 50,
        rerank_min_candidates: int = 10,
        hnsw_ef: int = 128,
        grounding_signal: str = "dense",
    ) -> None:
        self._store = store
        self._dense = dense
        self._sparse = sparse
        self._reranker = reranker
        self._dense_thresholds = dense_thresholds
        self._rerank_thresholds = rerank_thresholds
        self._prefetch = prefetch_limit
        self._rerank_candidates = rerank_candidates
        self._rerank_min = rerank_min_candidates
        self._hnsw_ef = hnsw_ef
        self._rerank_gate = grounding_signal == "rerank" and reranker is not None

    async def retrieve(
        self,
        scope: TenantScope,
        question: str,
        settings: RetrievalSettings,
        *,
        score_threshold: float | None = None,
    ) -> RetrievalResult:
        latency: dict[str, float] = {}
        sparse_indices: list[int] | None = None
        sparse_values: list[float] | None = None
        t0 = time.perf_counter()
        if settings.hybrid_enabled:
            dense_vecs, sparse_vecs = await asyncio.gather(
                self._dense.embed_queries([question]), self._sparse.encode_queries([question])
            )
            sparse = sparse_vecs[0]
            sparse_indices, sparse_values = sparse.indices, sparse.values
        else:
            dense_vecs = await self._dense.embed_queries([question])
        t1 = time.perf_counter()
        latency["embed"] = (t1 - t0) * 1000

        rerank = settings.rerank_enabled and self._reranker is not None
        hits = await self._store.hybrid_search(
            scope,
            dense_vecs[0],
            sparse_indices,
            sparse_values,
            limit=self._rerank_candidates if rerank else settings.top_k,
            prefetch_limit=self._prefetch,
            hnsw_ef=self._hnsw_ef,
        )
        t2 = time.perf_counter()
        latency["search"] = (t2 - t1) * 1000

        chunks = [_chunk(h) for h in hits]
        reranked = False
        rerank_error: str | None = None
        attempted = rerank and len(chunks) >= self._rerank_min
        if attempted:
            assert self._reranker is not None
            try:
                scores = await self._reranker.rerank(question, [c.text for c in chunks])
            except Exception as exc:  # degrade to the fused ranking, never fail the answer
                logger.warning("re-ranker failed, using fused ranking: %r", exc)
                rerank_error = type(exc).__name__
            else:
                for c, s in zip(chunks, scores, strict=True):
                    c.rerank_score = s
                    c.score = s
                chunks.sort(key=lambda c: c.rerank_score or 0.0, reverse=True)
                reranked = True
        chunks = chunks[: settings.top_k]
        checked = False
        if self._rerank_gate and not reranked and chunks:
            # Grounding check: the re-ranker judges the final top_k only (4 passages, not 50).
            attempted = True
            checked = await self._rerank_check(question, chunks)
            if not checked:
                rerank_error = "check_failed"
        latency["rerank"] = (time.perf_counter() - t2) * 1000 if attempted else 0.0

        use_rerank = reranked or checked
        thresholds = self._rerank_thresholds if use_rerank else self._dense_thresholds
        if not use_rerank and score_threshold is not None:
            mid = max(score_threshold, thresholds.conf_mid)
            thresholds = Thresholds(score_threshold, mid, max(mid, thresholds.conf_high))
        top_score = max((c.score for c in chunks), default=None)
        grounded = bool(chunks) and thresholds.is_grounded(top_score)
        latency["retrieval_total"] = (time.perf_counter() - t0) * 1000
        return RetrievalResult(
            chunks=chunks if grounded else [],
            top_score=top_score,
            confidence=thresholds.bucket(top_score) if grounded else Confidence.LOW,
            fallback=not grounded,
            reranked=reranked,
            latency_ms={k: round(v, 2) for k, v in latency.items()},
            candidates=chunks,
            rerank_error=rerank_error,
            rerank_checked=checked,
        )

    async def _rerank_check(self, question: str, chunks: list[RetrievedChunk]) -> bool:
        assert self._reranker is not None
        try:
            scores = await self._reranker.rerank(question, [c.text for c in chunks])
        except Exception as exc:  # degrade to the dense gate, never fail the answer
            logger.warning("re-ranker grounding check failed, using the dense gate: %r", exc)
            return False
        for c, s in zip(chunks, scores, strict=True):
            c.rerank_score = s
            c.score = s
        chunks.sort(key=lambda c: c.rerank_score or 0.0, reverse=True)
        return True


def _chunk(hit: ScoredChunk) -> RetrievedChunk:
    p = hit.payload
    return RetrievedChunk(
        source_id=str(p.get("source_id", "")),
        file_name=p.get("file_name"),
        page=p.get("page"),
        page_end=p.get("page_end"),
        section=p.get("section"),
        url=p.get("url"),
        title=p.get("title"),
        text=str(p.get("text", "")),
        score=hit.dense_score,
        dense_score=hit.dense_score,
    )
