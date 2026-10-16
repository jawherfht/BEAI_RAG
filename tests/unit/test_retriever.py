"""Retriever logic with an in-memory Qdrant and fake models."""

import uuid
from collections.abc import AsyncIterator, Sequence

import pytest
from qdrant_client import AsyncQdrantClient

from app.retrieval.confidence import Thresholds
from app.retrieval.retriever import RetrievalSettings, Retriever
from beai_rag_core.enums import Confidence
from beai_rag_core.qdrant_store import ChunkPoint, CollectionSpec, QdrantStore, point_id
from beai_rag_core.tenancy import TenantScope
from tests.fakes import HashingEmbedder, HashingSparse

DIM = 256
TEXTS = [
    "Returns are accepted within 30 days, unworn, with receipt.",
    "Standard shipping costs 4.90 EUR per order.",
    "Gift cards are valid for 3 years.",
    "Our stores are open Monday to Saturday from 10 am to 8 pm.",
] + [f"Filler paragraph number {i} about unrelated warehouse logistics." for i in range(12)]


class FakeReranker:
    def __init__(self) -> None:
        self.calls = 0

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        self.calls += 1
        return [0.95 if "Gift cards" in d else 0.01 for d in documents]

    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None


@pytest.fixture
async def setup() -> AsyncIterator[tuple[QdrantStore, TenantScope, HashingEmbedder]]:
    store = QdrantStore(AsyncQdrantClient(location=":memory:"), CollectionSpec("kb_r", DIM))
    await store.ensure_collection()
    dense, sparse = HashingEmbedder(DIM), HashingSparse()
    scope = TenantScope(uuid.uuid4(), uuid.uuid4())
    src = uuid.uuid4()
    dvecs = await dense.embed_documents(TEXTS)
    svecs = await sparse.encode_documents(TEXTS)
    await store.upsert(
        scope,
        [
            ChunkPoint(
                point_id(src, i, 1),
                d,
                s.indices,
                s.values,
                {"source_id": str(src), "file_name": "kb.pdf", "page": 1 + i // 4, "text": t},
            )
            for i, (t, d, s) in enumerate(zip(TEXTS, dvecs, svecs, strict=True))
        ],
    )
    yield store, scope, dense
    await store.close()


def retriever(
    store: QdrantStore,
    dense: HashingEmbedder,
    reranker: FakeReranker | None = None,
    min_candidates: int = 10,
) -> Retriever:
    return Retriever(
        store=store,
        dense=dense,
        sparse=HashingSparse(),
        reranker=reranker,
        dense_thresholds=Thresholds(0.30, 0.45, 0.60),
        rerank_thresholds=Thresholds(0.3, 0.5, 0.8),
        rerank_min_candidates=min_candidates,
    )


async def test_hybrid_finds_the_right_chunk_with_citation_fields(setup) -> None:  # type: ignore[no-untyped-def]
    store, scope, dense = setup
    r = await retriever(store, dense).retrieve(
        scope, "returns accepted within 30 days receipt", RetrievalSettings()
    )
    assert not r.fallback and len(r.chunks) == 4
    assert "30 days" in r.chunks[0].text and r.chunks[0].file_name == "kb.pdf"
    assert r.top_score == max(c.score for c in r.chunks)
    assert {"embed", "search", "retrieval_total"} <= set(r.latency_ms)


async def test_dense_only_mode(setup) -> None:  # type: ignore[no-untyped-def]
    store, scope, dense = setup
    r = await retriever(store, dense).retrieve(
        scope, "gift cards valid years", RetrievalSettings(hybrid_enabled=False)
    )
    assert "Gift cards" in r.chunks[0].text


async def test_below_threshold_is_fallback_without_sources(setup) -> None:  # type: ignore[no-untyped-def]
    store, scope, dense = setup
    r = await retriever(store, dense).retrieve(
        scope, "quantum chromodynamics lattice", RetrievalSettings()
    )
    assert r.fallback and r.chunks == [] and r.confidence is Confidence.LOW
    assert r.candidates  # ranking still available for evaluation


async def test_other_scope_sees_nothing(setup) -> None:  # type: ignore[no-untyped-def]
    store, scope, dense = setup
    other = TenantScope(uuid.uuid4(), scope.agent_id)
    r = await retriever(store, dense).retrieve(other, "returns within 30 days", RetrievalSettings())
    assert r.fallback and r.candidates == []


async def test_rerank_reorders_and_uses_rerank_score(setup) -> None:  # type: ignore[no-untyped-def]
    store, scope, dense = setup
    rr = FakeReranker()
    r = await retriever(store, dense, rr).retrieve(
        scope, "returns within 30 days", RetrievalSettings(top_k=4, rerank_enabled=True)
    )
    assert rr.calls == 1 and r.reranked
    assert "Gift cards" in r.chunks[0].text and r.chunks[0].rerank_score == 0.95
    assert r.top_score == 0.95 and r.confidence is Confidence.HIGH
    assert len(r.chunks) == 4


async def test_rerank_skipped_with_fewer_than_min_candidates(setup) -> None:  # type: ignore[no-untyped-def]
    store, scope, dense = setup
    rr = FakeReranker()
    r = await retriever(store, dense, rr, min_candidates=100).retrieve(
        scope, "returns within 30 days", RetrievalSettings(rerank_enabled=True)
    )
    assert rr.calls == 0 and not r.reranked and r.latency_ms["rerank"] == 0.0


async def test_per_kb_threshold_override(setup) -> None:  # type: ignore[no-untyped-def]
    store, scope, dense = setup
    r = await retriever(store, dense).retrieve(
        scope, "returns accepted within 30 days receipt", RetrievalSettings(), score_threshold=0.999
    )
    assert r.fallback


class BrokenReranker(FakeReranker):
    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        raise TimeoutError("re-ranker too slow")


async def test_reranker_failure_degrades_to_fused_ranking(setup) -> None:  # type: ignore[no-untyped-def]
    store, scope, dense = setup
    r = await retriever(store, dense, BrokenReranker()).retrieve(
        scope, "returns accepted within 30 days receipt", RetrievalSettings(rerank_enabled=True)
    )
    assert not r.reranked and r.rerank_error == "TimeoutError"
    assert not r.fallback and "30 days" in r.chunks[0].text  # dense thresholds applied
