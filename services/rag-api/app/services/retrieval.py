"""Retrieval for one agent: KB settings + cache + retriever (used by /test, /answer, gRPC)."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import NotFoundError
from app.resources import Resources
from app.retrieval.retriever import RetrievalResult, RetrievalSettings
from beai_rag_core.db import repositories as repo
from beai_rag_core.tenancy import TenantScope


@dataclass(frozen=True, slots=True)
class AgentKnowledge:
    kb_version: int
    rag_enabled: bool
    fallback_message: str
    settings: RetrievalSettings
    score_threshold: float | None


async def load_agent_knowledge(session: AsyncSession, scope: TenantScope) -> AgentKnowledge:
    kb = await repo.get_kb(session, scope)
    if kb is None:
        raise NotFoundError("This agent has no knowledge base yet")
    return AgentKnowledge(
        kb_version=kb.kb_version,
        rag_enabled=kb.rag_enabled,
        fallback_message=kb.fallback_message,
        settings=RetrievalSettings(
            top_k=kb.top_k, hybrid_enabled=kb.hybrid_enabled, rerank_enabled=kb.rerank_enabled
        ),
        score_threshold=kb.score_threshold,
    )


async def retrieve(
    resources: Resources, scope: TenantScope, knowledge: AgentKnowledge, question: str
) -> tuple[RetrievalResult, bool]:
    """Returns (result, cache_hit). The cache key includes tenant, agent and kb_version."""
    cached = await resources.retrieval_cache.get(scope, knowledge.kb_version, question)
    if cached is not None:
        result = RetrievalResult.from_dict(cached)
        result.latency_ms = {"cache": 0.0}
        return result, True
    result = await resources.retriever.retrieve(
        scope, question, knowledge.settings, score_threshold=knowledge.score_threshold
    )
    await resources.retrieval_cache.set(scope, knowledge.kb_version, question, result.to_dict())
    return result, False
