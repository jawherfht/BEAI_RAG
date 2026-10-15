"""Sources: file upload, URLs, business info, list, delete, reindex (spec sections 5 and 7).

Every write returns 202 immediately; parsing, crawling, chunking and embedding run in the
ingestion worker.
"""

from __future__ import annotations

import ipaddress
import json
import uuid
from typing import Annotated

from fastapi import APIRouter, File, UploadFile, status

from app.api.deps import ResourcesDep, SessionDep
from app.api.schemas import BusinessInfoIn, SourceAccepted, SourceOut, UrlSourceIn
from app.auth import AgentScopeDep
from app.domain.errors import ConflictError, NotFoundError, ValidationFailedError
from app.services.ingestion import add_job, commit_and_enqueue
from app.uploads import CheckedFile, UploadLimits, check_file, read_limited
from beai_rag_core.db import repositories as repo
from beai_rag_core.db.models import KnowledgeBase, Source
from beai_rag_core.embedding.factory import embed_model_tag
from beai_rag_core.enums import JobKind, SourceStatus, SourceType
from beai_rag_core.queue import IngestJob
from beai_rag_core.storage import source_object_key
from beai_rag_core.tenancy import TenantScope

router = APIRouter(prefix="/v1/agents/{agent_id}/sources", tags=["sources"])

BUSINESS_INFO_FILE_NAME = "Business info"
BUSINESS_INFO_OBJECT = "business-info.json"


async def _kb(resources: ResourcesDep, session: SessionDep, scope: TenantScope) -> KnowledgeBase:
    s = resources.settings
    return await repo.get_or_create_kb(
        session, scope, embed_model=s.embed_model, embed_model_version=embed_model_tag(s)
    )


@router.get("", response_model=list[SourceOut])
async def list_sources(scope: AgentScopeDep, session: SessionDep) -> list[SourceOut]:
    return [SourceOut.model_validate(s) for s in await repo.list_sources(session, scope)]


@router.post("/files", status_code=status.HTTP_202_ACCEPTED, response_model=list[SourceAccepted])
async def upload_files(
    files: Annotated[list[UploadFile], File(description="1..n documents")],
    scope: AgentScopeDep,
    session: SessionDep,
    resources: ResourcesDep,
) -> list[SourceAccepted]:
    settings = resources.settings
    if not files:
        raise ValidationFailedError("No files were sent")
    if len(files) > settings.max_files_per_upload:
        raise ValidationFailedError(f"At most {settings.max_files_per_upload} files per upload")
    limits = UploadLimits(
        max_bytes=settings.max_upload_mb * 1024 * 1024,
        max_zip_uncompressed_bytes=settings.max_zip_uncompressed_mb * 1024 * 1024,
        max_zip_entries=settings.max_zip_entries,
    )
    # Validate everything before writing anything.
    checked: list[CheckedFile] = []
    for upload in files:
        name = upload.filename or "file"
        checked.append(check_file(name, await read_limited(upload, limits.max_bytes), limits))

    kb = await _kb(resources, session, scope)
    accepted: list[SourceAccepted] = []
    jobs: list[IngestJob] = []
    seen: dict[str, uuid.UUID] = {}
    for f in checked:
        existing = await repo.find_source_by_sha256(session, scope, f.sha256)
        if existing is not None or f.sha256 in seen:
            sid = existing.id if existing is not None else seen[f.sha256]
            st = existing.status if existing is not None else SourceStatus.QUEUED
            accepted.append(
                SourceAccepted(source_id=sid, status=st, file_name=f.file_name, duplicate=True)
            )
            continue
        source_id = uuid.uuid4()
        key = source_object_key(scope, source_id, f.file_name)
        await resources.storage.put(key, f.data, f.mime_type)
        source = Source(
            id=source_id,
            knowledge_base_id=kb.id,
            tenant_id=scope.tenant_id,
            agent_id=scope.agent_id,
            type=SourceType.FILE,
            file_name=f.file_name,
            mime_type=f.mime_type,
            object_key=key,
            sha256=f.sha256,
            size_bytes=f.size,
            title=f.file_name,
            status=SourceStatus.QUEUED,
        )
        session.add(source)
        await session.flush()
        jobs.append(add_job(session, source, JobKind.INDEX))
        seen[f.sha256] = source_id
        accepted.append(
            SourceAccepted(source_id=source_id, status=source.status, file_name=f.file_name)
        )
    await commit_and_enqueue(resources, session, scope, jobs)
    return accepted


def _check_public_url(url: str) -> None:
    """Cheap pre-check; the crawler re-checks DNS results on every request (SSRF)."""
    from urllib.parse import urlsplit

    host = urlsplit(url).hostname or ""
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValidationFailedError("This URL cannot be crawled", details={"url": url})
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return
    if not ip.is_global:
        raise ValidationFailedError("This URL cannot be crawled", details={"url": url})


@router.post("/urls", status_code=status.HTTP_202_ACCEPTED, response_model=SourceAccepted)
async def add_url(
    body: UrlSourceIn, scope: AgentScopeDep, session: SessionDep, resources: ResourcesDep
) -> SourceAccepted:
    url = str(body.url)
    _check_public_url(url)
    existing = await repo.find_url_source(session, scope, url)
    if existing is not None:
        return SourceAccepted(
            source_id=existing.id, status=existing.status, url=url, duplicate=True
        )
    kb = await _kb(resources, session, scope)
    source = Source(
        id=uuid.uuid4(),
        knowledge_base_id=kb.id,
        tenant_id=scope.tenant_id,
        agent_id=scope.agent_id,
        type=SourceType.URL,
        url=url,
        crawl_depth=body.crawl_depth,
        max_pages=body.max_pages,
        recrawl_interval_hours=body.recrawl_interval_hours,
        status=SourceStatus.QUEUED,
    )
    session.add(source)
    await session.flush()
    job = add_job(session, source, JobKind.INDEX)
    await commit_and_enqueue(resources, session, scope, [job])
    return SourceAccepted(source_id=source.id, status=source.status, url=url)


@router.put("/business-info", status_code=status.HTTP_202_ACCEPTED, response_model=SourceAccepted)
async def put_business_info(
    body: BusinessInfoIn, scope: AgentScopeDep, session: SessionDep, resources: ResourcesDep
) -> SourceAccepted:
    if body.is_empty():
        raise ValidationFailedError("Business info is empty")
    kb = await _kb(resources, session, scope)
    source = await repo.find_business_info_source(session, scope)
    if source is None:
        source = Source(
            id=uuid.uuid4(),
            knowledge_base_id=kb.id,
            tenant_id=scope.tenant_id,
            agent_id=scope.agent_id,
            type=SourceType.BUSINESS_INFO,
            file_name=BUSINESS_INFO_FILE_NAME,
            mime_type="application/json",
            title=BUSINESS_INFO_FILE_NAME,
        )
        session.add(source)
    data = json.dumps(body.model_dump(), ensure_ascii=False).encode()
    source.object_key = source_object_key(scope, source.id, BUSINESS_INFO_OBJECT)
    source.size_bytes = len(data)
    source.status = SourceStatus.QUEUED
    source.error = None
    await resources.storage.put(source.object_key, data, "application/json")
    await session.flush()
    job = add_job(session, source, JobKind.INDEX)
    await commit_and_enqueue(resources, session, scope, [job])
    return SourceAccepted(
        source_id=source.id, status=source.status, file_name=BUSINESS_INFO_FILE_NAME
    )


async def _source_or_404(session: SessionDep, scope: TenantScope, source_id: str) -> Source:
    try:
        sid = uuid.UUID(source_id)
    except ValueError as exc:
        raise NotFoundError("Source not found") from exc
    source = await repo.get_source(session, scope, sid, lock=True)
    if source is None:
        raise NotFoundError("Source not found")
    return source


@router.delete("/{source_id}", status_code=status.HTTP_202_ACCEPTED, response_model=SourceAccepted)
async def delete_source(
    source_id: str, scope: AgentScopeDep, session: SessionDep, resources: ResourcesDep
) -> SourceAccepted:
    source = await _source_or_404(session, scope, source_id)
    if source.status is SourceStatus.DELETING:
        return SourceAccepted(source_id=source.id, status=source.status)
    source.status = SourceStatus.DELETING
    job = add_job(session, source, JobKind.DELETE)
    await commit_and_enqueue(resources, session, scope, [job])
    return SourceAccepted(source_id=source.id, status=SourceStatus.DELETING)


@router.post(
    "/{source_id}/reindex", status_code=status.HTTP_202_ACCEPTED, response_model=SourceAccepted
)
async def reindex_source(
    source_id: str, scope: AgentScopeDep, session: SessionDep, resources: ResourcesDep
) -> SourceAccepted:
    source = await _source_or_404(session, scope, source_id)
    if source.status is SourceStatus.DELETING:
        raise ConflictError("This source is being deleted")
    source.status = SourceStatus.QUEUED
    source.error = None
    job = add_job(session, source, JobKind.REINDEX)
    await commit_and_enqueue(resources, session, scope, [job])
    return SourceAccepted(source_id=source.id, status=SourceStatus.QUEUED)
