"""Ingestion worker entry point: ``python -m worker.main``."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal

import aio_pika

from beai_rag_core.db import repositories as repo
from beai_rag_core.db.session import make_engine, make_sessionmaker
from beai_rag_core.embedding import build_dense_embedder, build_sparse_encoder, build_token_counter
from beai_rag_core.embedding.factory import embed_model_tag
from beai_rag_core.enums import JobKind, SourceStatus
from beai_rag_core.qdrant_store import CollectionSpec, QdrantStore
from beai_rag_core.queue import IngestJob, QueuePublisher, declare_topology
from beai_rag_core.storage import ObjectStorage
from worker.config import WorkerSettings, get_settings
from worker.consumer import consume
from worker.contextualise import Contextualiser
from worker.parsers.docling_parser import DoclingParser
from worker.parsers.web_crawler import WebCrawler
from worker.pipeline import IngestionPipeline

logger = logging.getLogger(__name__)


def build_pipeline(settings: WorkerSettings) -> tuple[IngestionPipeline, QdrantStore]:
    api_key = settings.qdrant_api_key.get_secret_value() if settings.qdrant_api_key else None
    store = QdrantStore.connect(
        settings.qdrant_url,
        api_key,
        CollectionSpec(name=settings.qdrant_collection, dense_dim=settings.embed_dim),
        timeout_s=settings.qdrant_timeout_s,
    )
    contextualiser = (
        Contextualiser(
            settings.llm_base_url,
            settings.llm_model,
            settings.llm_key(),
            disable_thinking=settings.llm_disable_thinking,
            concurrency=settings.contextual_concurrency,
        )
        if settings.contextual_chunks
        else None
    )
    pipeline = IngestionPipeline(
        sessionmaker=make_sessionmaker(make_engine(settings.database_url, pool_size=5)),
        store=store,
        storage=ObjectStorage(settings),
        dense=build_dense_embedder(settings),
        sparse=build_sparse_encoder(settings),
        counter=build_token_counter(settings),
        parser=DoclingParser(
            ocr=settings.docling_ocr, artifacts_path=settings.docling_artifacts_path
        ),
        crawler=WebCrawler(),
        embed_model_tag=embed_model_tag(settings),
        contextualiser=contextualiser,
        max_pdf_pages=settings.max_pdf_pages,
    )
    return pipeline, store


async def recrawl_scheduler(settings: WorkerSettings, pipeline: IngestionPipeline) -> None:
    """Publishes ``ingest.recrawl`` jobs for URL sources whose interval has elapsed."""
    publisher = QueuePublisher(settings.rabbitmq_url.get_secret_value())
    sm = pipeline.sessionmaker
    try:
        while True:
            try:
                async with sm.begin() as session:
                    jobs: list[IngestJob] = []
                    for source in await repo.due_recrawls(session, repo.utcnow()):
                        row = repo.new_job(source, JobKind.RECRAWL)
                        session.add(row)
                        source.status = SourceStatus.QUEUED  # not re-scheduled next tick
                        jobs.append(
                            IngestJob(
                                job_id=row.id,
                                source_id=source.id,
                                tenant_id=source.tenant_id,
                                agent_id=source.agent_id,
                                kind=JobKind.RECRAWL,
                            )
                        )
                for job in jobs:
                    await publisher.publish(job)
            except Exception:
                logger.exception("recrawl scheduler tick failed")
            await asyncio.sleep(settings.recrawl_check_interval_s)
    finally:
        await publisher.close()


async def run(settings: WorkerSettings) -> None:
    pipeline, store = build_pipeline(settings)
    await store.ensure_collection()
    connection = await aio_pika.connect_robust(settings.rabbitmq_url.get_secret_value())
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=settings.worker_concurrency)
    await declare_topology(channel, settings.retry_base_ms)
    await consume(channel, pipeline, settings.retry_base_ms)
    scheduler = asyncio.create_task(recrawl_scheduler(settings, pipeline))
    logger.info("ingestion-worker consuming (concurrency=%d)", settings.worker_concurrency)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)
    await stop.wait()
    scheduler.cancel()
    await connection.close()
    await store.close()


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
