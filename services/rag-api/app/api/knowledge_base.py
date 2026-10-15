"""Knowledge-base settings and the Persona Builder status (spec section 7)."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from app.api.deps import ResourcesDep, SessionDep
from app.api.schemas import (
    KnowledgeBaseOut,
    KnowledgeBaseSettingsIn,
    KnowledgeBaseStatusOut,
    SourceCountsOut,
)
from app.auth import AgentScopeDep
from app.services.ingestion import add_job, commit_and_enqueue
from beai_rag_core import kb_rules
from beai_rag_core.db import repositories as repo
from beai_rag_core.db.models import DEFAULT_FALLBACK_MESSAGE, KnowledgeBase
from beai_rag_core.embedding.factory import embed_model_tag
from beai_rag_core.enums import JobKind, KnowledgeBaseStatus, SourceStatus

router = APIRouter(prefix="/v1/agents/{agent_id}", tags=["knowledge-base"])


def _out(
    kb: KnowledgeBase | None, agent_id: uuid.UUID, counts: repo.SourceCounts, **extra: bool
) -> KnowledgeBaseOut:
    counts_out = SourceCountsOut(
        files=counts.files, urls=counts.urls, business_info=counts.business_info
    )
    if kb is None:  # not configured yet: report the defaults, create nothing
        return KnowledgeBaseOut(
            agent_id=agent_id,
            status=KnowledgeBaseStatus.EMPTY,
            rag_enabled=True,
            chunk_size=kb_rules.CHUNK_SIZE_DEFAULT,
            chunk_overlap=kb_rules.overlap_for(kb_rules.CHUNK_SIZE_DEFAULT),
            top_k=kb_rules.TOP_K_DEFAULT,
            fallback_message=DEFAULT_FALLBACK_MESSAGE,
            hybrid_enabled=True,
            rerank_enabled=False,
            embed_model=None,
            kb_version=0,
            counts=counts_out,
        )
    return KnowledgeBaseOut(
        agent_id=kb.agent_id,
        status=kb.status,
        rag_enabled=kb.rag_enabled,
        chunk_size=kb.chunk_size,
        chunk_overlap=kb.chunk_overlap,
        top_k=kb.top_k,
        fallback_message=kb.fallback_message,
        hybrid_enabled=kb.hybrid_enabled,
        rerank_enabled=kb.rerank_enabled,
        embed_model=kb.embed_model,
        kb_version=kb.kb_version,
        counts=counts_out,
        **extra,
    )


@router.get("/knowledge-base", response_model=KnowledgeBaseOut)
async def get_knowledge_base(scope: AgentScopeDep, session: SessionDep) -> KnowledgeBaseOut:
    kb = await repo.get_kb(session, scope)
    counts = await repo.source_counts(session, scope)
    return _out(kb, scope.agent_id, counts)


@router.put("/knowledge-base", response_model=KnowledgeBaseOut)
async def put_knowledge_base(
    body: KnowledgeBaseSettingsIn,
    scope: AgentScopeDep,
    session: SessionDep,
    resources: ResourcesDep,
) -> KnowledgeBaseOut:
    settings = resources.settings
    kb = await repo.get_or_create_kb(
        session,
        scope,
        embed_model=settings.embed_model,
        embed_model_version=embed_model_tag(settings),
    )
    await session.refresh(kb, with_for_update=True)
    changes = body.model_dump(exclude_none=True)
    changed = {k: v for k, v in changes.items() if getattr(kb, k) != v}
    for key, value in changed.items():
        setattr(kb, key, value)

    jobs = []
    if "chunk_size" in changed:
        kb.chunk_overlap = kb_rules.overlap_for(kb.chunk_size)
        # Re-chunk + re-embed every source of this agent only (blue/green in the worker).
        for source in await repo.list_sources(session, scope):
            if source.status is SourceStatus.DELETING:
                continue
            source.status = SourceStatus.QUEUED
            source.error = None
            jobs.append(add_job(session, source, JobKind.REINDEX))
    if changed:
        await session.flush()
        await repo.bump_kb_version(session, kb.id)
    await commit_and_enqueue(resources, session, scope, jobs)
    await session.refresh(kb)
    counts = await repo.source_counts(session, scope)
    return _out(kb, scope.agent_id, counts, reindexing=bool(jobs))


def status_label(files: int, rag_enabled: bool) -> str:
    noun = "file" if files == 1 else "files"
    return f"Knowledge base: {files} {noun}, RAG {'on' if rag_enabled else 'off'}"


@router.get("/knowledge-base/status", response_model=KnowledgeBaseStatusOut)
async def get_knowledge_base_status(
    scope: AgentScopeDep, session: SessionDep
) -> KnowledgeBaseStatusOut:
    kb = await repo.get_kb(session, scope)
    counts = await repo.source_counts(session, scope)
    rag_enabled = kb.rag_enabled if kb is not None else True
    return KnowledgeBaseStatusOut(
        files=counts.files,
        urls=counts.urls,
        rag_enabled=rag_enabled,
        status=kb.status if kb is not None else KnowledgeBaseStatus.EMPTY,
        label=status_label(counts.files, rag_enabled),
    )
