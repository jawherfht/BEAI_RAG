"""Ingestion pipeline: parse -> chunk -> contextualise -> embed -> upsert (spec section 5).

All heavy work happens here, off the live query path. Each step updates the source status
(queued -> parsing -> chunking -> embedding -> ready | error) in its own short transaction.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from beai_rag_core.db import repositories as repo
from beai_rag_core.embedding.base import DenseEmbedder, SparseEncoder, TokenCounter
from beai_rag_core.enums import JobKind, JobStatus, SourceStatus, SourceType
from beai_rag_core.qdrant_store import ChunkPoint, QdrantStore, point_id
from beai_rag_core.queue import IngestJob
from beai_rag_core.storage import ObjectStorage, parsed_cache_key, source_prefix
from beai_rag_core.tenancy import TenantScope
from worker.chunking.chunker import Chunk, Chunker
from worker.contextualise import Contextualiser
from worker.language import detect_language
from worker.parsers.base import ParsedDocument, ParseError
from worker.parsers.business_info import BUSINESS_INFO_FILE_NAME, render_business_info

logger = logging.getLogger(__name__)


class FileParser(Protocol):
    def parse(
        self, path: Path, mime_type: str, *, max_pages: int | None = None
    ) -> ParsedDocument: ...


class Crawler(Protocol):
    async def crawl(
        self, start_url: str, crawl_depth: int = 1, max_pages: int = 50
    ) -> ParsedDocument: ...


@dataclass(frozen=True, slots=True)
class SourceSnapshot:
    """Plain copy of the source row, so no ORM object outlives its session."""

    scope: TenantScope
    source_id: object
    knowledge_base_id: object
    type: SourceType
    file_name: str | None
    mime_type: str | None
    object_key: str | None
    url: str | None
    crawl_depth: int
    max_pages: int
    content_hash: str | None
    kb_version: int
    chunk_size: int
    chunk_overlap: int


class SourceGoneError(Exception):
    """The source was deleted (or is being deleted) while the job ran."""


class IngestionPipeline:
    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        store: QdrantStore,
        storage: ObjectStorage,
        dense: DenseEmbedder,
        sparse: SparseEncoder,
        counter: TokenCounter,
        parser: FileParser,
        crawler: Crawler,
        embed_model_tag: str,
        contextualiser: Contextualiser | None = None,
        max_pdf_pages: int | None = None,
        upsert_batch_size: int = 128,
    ) -> None:
        self._sm = sessionmaker
        self._store = store
        self._storage = storage
        self._dense = dense
        self._sparse = sparse
        self._counter = counter
        self._parser = parser
        self._crawler = crawler
        self._embed_model_tag = embed_model_tag
        self._contextualiser = contextualiser
        self._max_pdf_pages = max_pdf_pages
        self._batch = upsert_batch_size

    @property
    def sessionmaker(self) -> async_sessionmaker[AsyncSession]:
        return self._sm

    # ---- entry point -------------------------------------------------------------------

    async def run(self, job: IngestJob) -> None:
        if job.kind is JobKind.DELETE:
            await self._delete(job)
            return
        try:
            await self._index(job)
        except SourceGoneError:
            logger.info("source %s deleted during indexing; cleaning up", job.source_id)
            scope = TenantScope(job.tenant_id, job.agent_id)
            await self._store.delete_source(scope, job.source_id)

    # ---- index / reindex / recrawl ------------------------------------------------------

    async def _index(self, job: IngestJob) -> None:
        timings: dict[str, float] = {}
        t0 = time.monotonic()
        snap = await self._start(job)
        doc = await self._parsed_document(job, snap)
        timings["parse"] = time.monotonic() - t0
        if (
            job.kind is JobKind.RECRAWL
            and doc.content_hash
            and doc.content_hash == snap.content_hash
        ):
            logger.info("recrawl of %s: content unchanged, skipping re-embed", snap.url)
            await self._finish_unchanged(job, snap)
            return

        await self._set_status(job, SourceStatus.CHUNKING)
        if doc.language is None:
            doc.language = await asyncio.to_thread(detect_language, doc.plain_text(4000))
        t = time.monotonic()
        chunks = Chunker(self._counter, snap.chunk_size, snap.chunk_overlap).chunk(doc)
        timings["chunk"] = time.monotonic() - t
        if not chunks:
            raise ParseError("No text could be extracted from this source")

        await self._set_status(job, SourceStatus.EMBEDDING)
        t = time.monotonic()
        prefixes = await self._prefixes(doc, chunks)
        embed_inputs = [
            f"{p}\n{c.text}" if p else c.text for p, c in zip(prefixes, chunks, strict=True)
        ]
        dense = await self._dense.embed_documents(embed_inputs)
        sparse = await self._sparse.encode_documents(embed_inputs)
        timings["embed"] = time.monotonic() - t
        t = time.monotonic()
        points = [
            ChunkPoint(
                id=point_id(job.source_id, c.index, snap.kb_version),
                dense=d,
                sparse_indices=s.indices,
                sparse_values=s.values,
                payload=self._payload(snap, doc, c, prefix),
            )
            for c, d, s, prefix in zip(chunks, dense, sparse, prefixes, strict=True)
        ]
        # Blue/green: write the new points first, then drop the old ones.
        await self._store.upsert_batched(snap.scope, points, self._batch)
        await self._store.delete_stale_points(snap.scope, job.source_id, [p.id for p in points])
        timings["upsert"] = time.monotonic() - t
        await self._finish(job, snap, doc, len(chunks))
        logger.info(
            "indexed source %s: pages=%s chunks=%d %s total=%.1fs",
            job.source_id,
            doc.pages,
            len(chunks),
            " ".join(f"{k}={v:.1f}s" for k, v in timings.items()),
            time.monotonic() - t0,
        )

    async def _start(self, job: IngestJob) -> SourceSnapshot:
        async with self._sm.begin() as session:
            source = await repo.load_source_for_job(
                session, job.source_id, job.tenant_id, job.agent_id
            )
            if source is None or source.status is SourceStatus.DELETING:
                raise SourceGoneError
            scope = TenantScope(source.tenant_id, source.agent_id)
            kb = await repo.get_kb(session, scope)
            if kb is None:
                raise SourceGoneError
            source.status = SourceStatus.PARSING
            source.error = None
            await self._job_running(session, job)
            await repo.refresh_kb_status(session, scope)
            return SourceSnapshot(
                scope=scope,
                source_id=source.id,
                knowledge_base_id=kb.id,
                type=source.type,
                file_name=source.file_name,
                mime_type=source.mime_type,
                object_key=source.object_key,
                url=source.url,
                crawl_depth=source.crawl_depth,
                max_pages=source.max_pages,
                content_hash=source.sha256 if source.type is SourceType.URL else None,
                kb_version=kb.kb_version,
                chunk_size=kb.chunk_size,
                chunk_overlap=kb.chunk_overlap,
            )

    async def _parsed_document(self, job: IngestJob, snap: SourceSnapshot) -> ParsedDocument:
        cache_key = parsed_cache_key(snap.scope, job.source_id)
        # A source's stored file never changes (business info deletes the cache on update), so
        # reindex jobs and retries re-chunk from the cache; only a recrawl must fetch again.
        if job.kind is not JobKind.RECRAWL:
            cached = await self._storage.get_optional(cache_key)
            if cached is not None:
                return ParsedDocument.from_json(json.loads(cached))
        doc = await self._parse(snap)
        await self._storage.put(cache_key, json.dumps(doc.to_json()).encode(), "application/json")
        return doc

    async def _parse(self, snap: SourceSnapshot) -> ParsedDocument:
        if snap.type is SourceType.URL:
            assert snap.url is not None
            return await self._crawler.crawl(snap.url, snap.crawl_depth, snap.max_pages)
        assert snap.object_key is not None
        data = await self._storage.get(snap.object_key)
        if snap.type is SourceType.BUSINESS_INFO:
            return render_business_info(json.loads(data))
        assert snap.mime_type is not None
        suffix = Path(snap.file_name or "file").suffix
        with tempfile.TemporaryDirectory(prefix="beai-ingest-") as tmp:
            path = Path(tmp) / f"source{suffix}"
            path.write_bytes(data)
            max_pages = self._max_pdf_pages if snap.mime_type == "application/pdf" else None
            return await asyncio.to_thread(
                self._parser.parse, path, snap.mime_type, max_pages=max_pages
            )

    async def _prefixes(self, doc: ParsedDocument, chunks: list[Chunk]) -> list[str]:
        if self._contextualiser is None:
            return [""] * len(chunks)
        return await self._contextualiser.prefixes(
            doc.title or "", doc.plain_text(6000), [c.text for c in chunks]
        )

    def _payload(
        self, snap: SourceSnapshot, doc: ParsedDocument, chunk: Chunk, prefix: str
    ) -> dict[str, object]:
        if snap.type is SourceType.BUSINESS_INFO:
            file_name: str | None = BUSINESS_INFO_FILE_NAME
        elif snap.type is SourceType.FILE:
            file_name = snap.file_name
        else:
            file_name = None
        return {
            "knowledge_base_id": str(snap.knowledge_base_id),
            "source_id": str(snap.source_id),
            "source_type": snap.type.value,
            "file_name": file_name,
            "url": chunk.url,
            "title": chunk.title if snap.type is SourceType.URL else doc.title,
            "page": chunk.page,
            "page_end": chunk.page_end,
            "section": chunk.section,
            "chunk_index": chunk.index,
            "text": chunk.text,
            "context_prefix": prefix or None,
            "lang": doc.language,
            "embed_model": self._embed_model_tag,
            "kb_version": snap.kb_version,
            "created_at": repo.utcnow().isoformat(),
        }

    async def _finish(
        self, job: IngestJob, snap: SourceSnapshot, doc: ParsedDocument, n_chunks: int
    ) -> None:
        async with self._sm.begin() as session:
            source = await repo.get_source(session, snap.scope, job.source_id, lock=True)
            if source is None or source.status is SourceStatus.DELETING:
                raise SourceGoneError
            source.status = SourceStatus.READY
            source.error = None
            source.chunks = n_chunks
            source.pages = doc.pages
            source.language = doc.language
            source.title = doc.title or source.title
            source.last_indexed_at = repo.utcnow()
            if source.type is SourceType.URL:
                source.sha256 = doc.content_hash
            await self._job_done(session, job, JobStatus.SUCCEEDED)
            await self._bump(session, snap.scope)

    async def _finish_unchanged(self, job: IngestJob, snap: SourceSnapshot) -> None:
        async with self._sm.begin() as session:
            source = await repo.get_source(session, snap.scope, job.source_id, lock=True)
            if source is None:
                raise SourceGoneError
            source.status = SourceStatus.READY
            source.last_indexed_at = repo.utcnow()
            await self._job_done(session, job, JobStatus.SUCCEEDED)
            await repo.refresh_kb_status(session, snap.scope)

    async def _set_status(self, job: IngestJob, status: SourceStatus) -> None:
        async with self._sm.begin() as session:
            scope = TenantScope(job.tenant_id, job.agent_id)
            source = await repo.get_source(session, scope, job.source_id, lock=True)
            if source is None or source.status is SourceStatus.DELETING:
                raise SourceGoneError
            source.status = status

    # ---- delete ------------------------------------------------------------------------

    async def _delete(self, job: IngestJob) -> None:
        scope = TenantScope(job.tenant_id, job.agent_id)
        await self._store.delete_source(scope, job.source_id)
        await self._storage.delete_prefix(source_prefix(scope, job.source_id))
        async with self._sm.begin() as session:
            source = await repo.get_source(session, scope, job.source_id, lock=True)
            if source is not None:
                await session.delete(source)
                await session.flush()
            await self._bump(session, scope)

    # ---- failure handling (called by the consumer) ---------------------------------------

    async def mark_retrying(self, job: IngestJob, error: str) -> None:
        async with self._sm.begin() as session:
            j = await repo.get_job(session, job.job_id)
            if j is not None:
                j.status = JobStatus.QUEUED
                j.error = error
            source = await repo.get_source(
                session, TenantScope(job.tenant_id, job.agent_id), job.source_id, lock=True
            )
            if source is not None and source.status is not SourceStatus.DELETING:
                source.status = SourceStatus.QUEUED

    async def mark_failed(self, job: IngestJob, error: str, *, dead_lettered: bool) -> None:
        scope = TenantScope(job.tenant_id, job.agent_id)
        async with self._sm.begin() as session:
            j = await repo.get_job(session, job.job_id)
            if j is not None:
                j.status = JobStatus.DEAD_LETTERED if dead_lettered else JobStatus.FAILED
                j.error = error
                j.finished_at = repo.utcnow()
            source = await repo.get_source(session, scope, job.source_id, lock=True)
            if source is not None and source.status is not SourceStatus.DELETING:
                source.status = SourceStatus.ERROR
                source.error = error
            await repo.refresh_kb_status(session, scope)

    # ---- helpers -----------------------------------------------------------------------

    async def _job_running(self, session: AsyncSession, job: IngestJob) -> None:
        j = await repo.get_job(session, job.job_id)
        if j is not None:
            j.status = JobStatus.RUNNING
            j.attempts += 1
            j.started_at = repo.utcnow()

    async def _job_done(self, session: AsyncSession, job: IngestJob, status: JobStatus) -> None:
        j = await repo.get_job(session, job.job_id)
        if j is not None:
            j.status = status
            j.error = None
            j.finished_at = repo.utcnow()

    async def _bump(self, session: AsyncSession, scope: TenantScope) -> None:
        kb = await repo.get_kb(session, scope, lock=True)
        if kb is not None:
            await repo.bump_kb_version(session, kb.id)
            await repo.refresh_kb_status(session, scope)
