"""Tenant-scoped data access for knowledge bases, sources and jobs.

Every query filters on the ``TenantScope`` (tenant_id AND agent_id). Functions that take an
id (source, job) still require the scope, so an id from another tenant is simply not found.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from beai_rag_core.db.models import IngestionJob, KnowledgeBase, Source
from beai_rag_core.enums import (
    JobKind,
    JobStatus,
    KnowledgeBaseStatus,
    SourceStatus,
    SourceType,
)
from beai_rag_core.tenancy import TenantScope

PROCESSING = frozenset(
    {
        SourceStatus.QUEUED,
        SourceStatus.PARSING,
        SourceStatus.CHUNKING,
        SourceStatus.EMBEDDING,
        SourceStatus.DELETING,
    }
)


def _kb_query(scope: TenantScope) -> Select[KnowledgeBase]:
    return select(KnowledgeBase).where(
        KnowledgeBase.tenant_id == scope.tenant_id, KnowledgeBase.agent_id == scope.agent_id
    )


async def get_kb(
    session: AsyncSession, scope: TenantScope, *, lock: bool = False
) -> KnowledgeBase | None:
    q = _kb_query(scope)
    if lock:
        q = q.with_for_update()
    result: KnowledgeBase | None = (await session.execute(q)).scalar_one_or_none()
    return result


async def get_or_create_kb(
    session: AsyncSession,
    scope: TenantScope,
    *,
    embed_model: str | None = None,
    embed_model_version: str | None = None,
) -> KnowledgeBase:
    kb = await get_kb(session, scope)
    if kb is None:
        kb = KnowledgeBase(
            tenant_id=scope.tenant_id,
            agent_id=scope.agent_id,
            embed_model=embed_model,
            embed_model_version=embed_model_version,
        )
        session.add(kb)
        await session.flush()
        await session.refresh(kb)
    return kb


async def list_sources(session: AsyncSession, scope: TenantScope) -> list[Source]:
    q = (
        select(Source)
        .where(Source.tenant_id == scope.tenant_id, Source.agent_id == scope.agent_id)
        .order_by(Source.created_at)
    )
    return list((await session.execute(q)).scalars())


async def get_source(
    session: AsyncSession, scope: TenantScope, source_id: uuid.UUID, *, lock: bool = False
) -> Source | None:
    q = select(Source).where(
        Source.id == source_id,
        Source.tenant_id == scope.tenant_id,
        Source.agent_id == scope.agent_id,
    )
    if lock:
        q = q.with_for_update()
    result: Source | None = (await session.execute(q)).scalar_one_or_none()
    return result


async def find_source_by_sha256(
    session: AsyncSession, scope: TenantScope, sha256: str
) -> Source | None:
    q = select(Source).where(
        Source.tenant_id == scope.tenant_id,
        Source.agent_id == scope.agent_id,
        Source.type == SourceType.FILE,
        Source.sha256 == sha256,
        Source.status != SourceStatus.DELETING,
    )
    return (await session.execute(q)).scalars().first()


async def find_url_source(session: AsyncSession, scope: TenantScope, url: str) -> Source | None:
    q = select(Source).where(
        Source.tenant_id == scope.tenant_id,
        Source.agent_id == scope.agent_id,
        Source.type == SourceType.URL,
        Source.url == url,
        Source.status != SourceStatus.DELETING,
    )
    return (await session.execute(q)).scalars().first()


async def find_business_info_source(session: AsyncSession, scope: TenantScope) -> Source | None:
    q = select(Source).where(
        Source.tenant_id == scope.tenant_id,
        Source.agent_id == scope.agent_id,
        Source.type == SourceType.BUSINESS_INFO,
        Source.status != SourceStatus.DELETING,
    )
    return (await session.execute(q)).scalars().first()


def new_job(source: Source, kind: JobKind) -> IngestionJob:
    return IngestionJob(id=uuid.uuid4(), source_id=source.id, kind=kind, status=JobStatus.QUEUED)


async def get_job(session: AsyncSession, job_id: uuid.UUID) -> IngestionJob | None:
    result: IngestionJob | None = await session.get(IngestionJob, job_id)
    return result


async def bump_kb_version(session: AsyncSession, kb_id: uuid.UUID) -> int:
    """Atomically increment kb_version (the answer-cache key) and return the new value."""
    result = await session.execute(
        update(KnowledgeBase)
        .where(KnowledgeBase.id == kb_id)
        .values(kb_version=KnowledgeBase.kb_version + 1, updated_at=func.now())
        .returning(KnowledgeBase.kb_version)
    )
    version: int = result.scalar_one()
    return version


def kb_status_for(statuses: list[SourceStatus]) -> KnowledgeBaseStatus:
    active = [s for s in statuses if s != SourceStatus.DELETING]
    if any(s in PROCESSING for s in statuses):
        return KnowledgeBaseStatus.INDEXING
    if not active:
        return KnowledgeBaseStatus.EMPTY
    if any(s == SourceStatus.READY for s in active):
        return KnowledgeBaseStatus.READY
    return KnowledgeBaseStatus.ERROR


async def refresh_kb_status(session: AsyncSession, scope: TenantScope) -> KnowledgeBaseStatus:
    kb = await get_kb(session, scope, lock=True)
    if kb is None:
        return KnowledgeBaseStatus.EMPTY
    statuses = [s.status for s in await list_sources(session, scope)]
    kb.status = kb_status_for(statuses)
    return kb.status


@dataclass(frozen=True, slots=True)
class SourceCounts:
    files: int
    urls: int
    business_info: int


async def source_counts(session: AsyncSession, scope: TenantScope) -> SourceCounts:
    q = (
        select(Source.type, func.count())
        .where(
            Source.tenant_id == scope.tenant_id,
            Source.agent_id == scope.agent_id,
            Source.status != SourceStatus.DELETING,
        )
        .group_by(Source.type)
    )
    counts = {t: n for t, n in (await session.execute(q)).all()}
    return SourceCounts(
        files=counts.get(SourceType.FILE, 0),
        urls=counts.get(SourceType.URL, 0),
        business_info=counts.get(SourceType.BUSINESS_INFO, 0),
    )


def utcnow() -> datetime:
    return datetime.now(UTC)


async def load_source_for_job(
    session: AsyncSession, source_id: uuid.UUID, tenant_id: uuid.UUID, agent_id: uuid.UUID
) -> Source | None:
    """Worker side: the job message names the scope; the row must agree with it."""
    return await get_source(session, TenantScope(tenant_id, agent_id), source_id, lock=True)


async def due_recrawls(session: AsyncSession, now: datetime) -> list[Source]:
    """URL sources whose re-crawl interval has elapsed (worker scheduler, all tenants)."""
    q = select(Source).where(
        Source.type == SourceType.URL,
        Source.recrawl_interval_hours.is_not(None),
        Source.status == SourceStatus.READY,
        Source.last_indexed_at.is_not(None),
        Source.last_indexed_at
        < now - func.make_interval(0, 0, 0, 0, Source.recrawl_interval_hours),
    )
    return list((await session.execute(q)).scalars())
