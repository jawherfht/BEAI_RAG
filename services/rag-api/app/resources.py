"""Long-lived clients created at startup and closed at shutdown."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.cache.answer_cache import AnswerCache
from app.config import Settings
from app.generation.llm import LLMClient, OpenAICompatibleClient
from app.retrieval.confidence import Thresholds
from app.retrieval.reranker import LocalReranker, Reranker, VllmReranker
from app.retrieval.retriever import Retriever
from beai_rag_core.db.session import make_engine, make_sessionmaker
from beai_rag_core.embedding import build_dense_embedder, build_sparse_encoder
from beai_rag_core.embedding.base import DenseEmbedder, SparseEncoder
from beai_rag_core.qdrant_store import CollectionSpec, QdrantStore
from beai_rag_core.queue import QueuePublisher
from beai_rag_core.storage import ObjectStorage

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ModelOverrides:
    """Inject model clients (tests, tools). ``None`` = build from settings."""

    dense: DenseEmbedder | None = None
    sparse: SparseEncoder | None = None
    reranker: Reranker | None = None
    llm: LLMClient | None = None


def build_llm(settings: Settings) -> LLMClient:
    """Provider switch is configuration only (LLM_BASE_URL, LLM_MODEL, LLM_THINKING_SWITCH)."""
    return OpenAICompatibleClient(
        settings.llm_base_url,
        settings.llm_model,
        api_key=settings.llm_key(),
        disable_thinking=settings.llm_disable_thinking,
        thinking_switch=settings.llm_thinking_switch,
        timeout_s=settings.llm_timeout_s,
        max_retries=settings.llm_max_retries,
        retry_base_s=settings.llm_retry_base_s,
        retry_max_wait_s=settings.llm_retry_max_wait_s,
    )


def build_reranker(settings: Settings) -> Reranker | None:
    if settings.rerank_provider == "none":
        return None
    if settings.rerank_provider == "vllm":
        return VllmReranker(
            settings.rerank_url,
            settings.rerank_model,
            instruction=settings.rerank_instruction,
            api_key=settings.llm_key(),
            timeout_s=settings.rerank_timeout_s,
        )
    return LocalReranker(settings.rerank_url, timeout_s=settings.rerank_timeout_s)


@dataclass(slots=True)
class Resources:
    settings: Settings
    store: QdrantStore
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    redis: Redis
    storage: ObjectStorage
    publisher: QueuePublisher
    dense: DenseEmbedder
    sparse: SparseEncoder
    reranker: Reranker | None
    retriever: Retriever
    retrieval_cache: AnswerCache
    answer_cache: AnswerCache
    llm: LLMClient
    grpc_port: int | None = None

    @classmethod
    def create(cls, settings: Settings, overrides: ModelOverrides | None = None) -> Resources:
        o = overrides or ModelOverrides()
        api_key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
        store = QdrantStore.connect(
            settings.qdrant_url,
            api_key,
            CollectionSpec(name=settings.qdrant_collection, dense_dim=settings.embed_dim),
            timeout_s=settings.qdrant_timeout_s,
        )
        engine = make_engine(settings.database_url)
        dense = o.dense or build_dense_embedder(settings)
        sparse = o.sparse or build_sparse_encoder(settings)
        reranker = o.reranker if o.reranker is not None else build_reranker(settings)
        redis = Redis.from_url(settings.redis_url, socket_timeout=settings.readiness_timeout_s)
        retriever = Retriever(
            store=store,
            dense=dense,
            sparse=sparse,
            reranker=reranker,
            dense_thresholds=Thresholds(
                settings.score_threshold, settings.conf_mid, settings.conf_high
            ),
            rerank_thresholds=Thresholds(
                settings.rerank_score_threshold, settings.rerank_conf_mid, settings.rerank_conf_high
            ),
            prefetch_limit=settings.search_prefetch_limit,
            rerank_candidates=settings.rerank_candidates,
            rerank_min_candidates=settings.rerank_min_candidates,
            hnsw_ef=settings.search_hnsw_ef,
        )
        return cls(
            settings=settings,
            store=store,
            engine=engine,
            sessionmaker=make_sessionmaker(engine),
            redis=redis,
            storage=ObjectStorage(settings),
            publisher=QueuePublisher(settings.rabbitmq_url.get_secret_value()),
            dense=dense,
            sparse=sparse,
            reranker=reranker,
            retriever=retriever,
            retrieval_cache=AnswerCache(redis, settings.answer_cache_ttl_s, kind="retrieval"),
            answer_cache=AnswerCache(redis, settings.answer_cache_ttl_s, kind="answer"),
            llm=o.llm or build_llm(settings),
        )

    async def bootstrap(self) -> None:
        """Idempotent dev bootstrap. Failures are logged; /readyz reports them."""
        if self.settings.qdrant_auto_create:
            try:
                if await self.store.ensure_collection():
                    logger.info("created Qdrant collection %s", self.store.collection)
            except Exception:
                logger.exception("could not ensure Qdrant collection")
        if self.settings.s3_auto_create_bucket:
            try:
                await self.storage.ensure_bucket()
            except Exception:
                logger.exception("could not ensure object storage bucket")
        # Load the BM25 model now so the first live query does not pay for it.
        warm_up = getattr(self.sparse, "warm_up", None)
        if callable(warm_up):
            try:
                await asyncio.to_thread(warm_up)
            except Exception:
                logger.exception("could not load the sparse (BM25) model")

    async def close(self) -> None:
        await self.publisher.close()
        await self.store.close()
        await self.dense.close()
        await self.llm.close()
        if self.reranker is not None:
            await self.reranker.close()
        await self.redis.aclose()
        await self.engine.dispose()
