"""Long-lived clients created at startup and closed at shutdown."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.config import Settings
from beai_rag_core.db.session import make_engine, make_sessionmaker
from beai_rag_core.qdrant_store import CollectionSpec, QdrantStore
from beai_rag_core.queue import QueuePublisher
from beai_rag_core.storage import ObjectStorage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Resources:
    settings: Settings
    store: QdrantStore
    engine: AsyncEngine
    sessionmaker: async_sessionmaker[AsyncSession]
    redis: Redis
    storage: ObjectStorage
    publisher: QueuePublisher

    @classmethod
    def create(cls, settings: Settings) -> Resources:
        api_key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
        store = QdrantStore.connect(
            settings.qdrant_url,
            api_key,
            CollectionSpec(name=settings.qdrant_collection, dense_dim=settings.embed_dim),
            timeout_s=settings.qdrant_timeout_s,
        )
        engine = make_engine(settings.database_url)
        return cls(
            settings=settings,
            store=store,
            engine=engine,
            sessionmaker=make_sessionmaker(engine),
            redis=Redis.from_url(settings.redis_url, socket_timeout=settings.readiness_timeout_s),
            storage=ObjectStorage(settings),
            publisher=QueuePublisher(settings.rabbitmq_url.get_secret_value()),
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

    async def close(self) -> None:
        await self.publisher.close()
        await self.store.close()
        await self.redis.aclose()
        await self.engine.dispose()
