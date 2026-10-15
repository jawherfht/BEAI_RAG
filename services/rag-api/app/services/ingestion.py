"""Creating sources and jobs, then handing them to the queue (spec section 5, step 1)."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import ServiceUnavailableError
from app.resources import Resources
from beai_rag_core.db import repositories as repo
from beai_rag_core.db.models import IngestionJob, Source
from beai_rag_core.enums import JobKind, JobStatus, SourceStatus
from beai_rag_core.queue import IngestJob
from beai_rag_core.tenancy import TenantScope

logger = logging.getLogger(__name__)

QUEUE_FAILED_MESSAGE = "Could not queue this source for indexing. Please try again."


def add_job(session: AsyncSession, source: Source, kind: JobKind) -> IngestJob:
    job: IngestionJob = repo.new_job(source, kind)
    session.add(job)
    return IngestJob(
        job_id=job.id,
        source_id=source.id,
        tenant_id=source.tenant_id,
        agent_id=source.agent_id,
        kind=kind,
    )


async def commit_and_enqueue(
    resources: Resources, session: AsyncSession, scope: TenantScope, jobs: list[IngestJob]
) -> None:
    """Commit first (the worker must find the rows), then publish.

    If the broker is down the jobs are marked failed and the sources show a clear error, so
    nothing stays "queued" forever; the caller gets 503 and can retry.
    """
    await repo.refresh_kb_status(session, scope)
    await session.commit()
    failed: list[IngestJob] = []
    for job in jobs:
        try:
            await resources.publisher.publish(job)
        except Exception:
            logger.exception("publish failed for job %s", job.job_id)
            failed.append(job)
    if not failed:
        return
    for job in failed:
        j = await repo.get_job(session, job.job_id)
        if j is not None:
            j.status = JobStatus.FAILED
            j.error = QUEUE_FAILED_MESSAGE
        source = await repo.get_source(session, scope, job.source_id)
        if source is not None and job.kind is not JobKind.DELETE:
            source.status = SourceStatus.ERROR
            source.error = QUEUE_FAILED_MESSAGE
    await repo.refresh_kb_status(session, scope)
    await session.commit()
    raise ServiceUnavailableError(QUEUE_FAILED_MESSAGE, details={"queued": len(jobs) - len(failed)})
