"""gRPC RagService for the Interaction Agents Service (spec section 7).

Tenant and agent travel in call metadata (``x-beai-tenant-id``, ``x-beai-agent-id``) set by the
trusted caller, never in the message body. Metadata can only be trusted when the caller is
authenticated, so the server requires mTLS (client certificates signed by GRPC_CLIENT_CA);
``GRPC_ALLOW_INSECURE=true`` starts a plaintext port for local development only.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import grpc

from app.domain.errors import AppError, NotFoundError
from app.generation.prompt import Persona, Turn
from app.grpc_gen.beai.rag.v1 import rag_pb2, rag_pb2_grpc
from app.resources import Resources
from app.services.answer import AnswerRequest, AnswerService, DoneEvent, TokenEvent
from app.services.retrieval import load_agent_knowledge, retrieve
from beai_rag_core.db import repositories as repo
from beai_rag_core.enums import Confidence, KnowledgeBaseStatus
from beai_rag_core.tenancy import TenantScope

logger = logging.getLogger(__name__)

_DEFAULT_PERSONA = Persona()
TENANT_KEY = "x-beai-tenant-id"
AGENT_KEY = "x-beai-agent-id"
_CONF = {
    Confidence.LOW: rag_pb2.CONFIDENCE_LOW,
    Confidence.MEDIUM: rag_pb2.CONFIDENCE_MEDIUM,
    Confidence.HIGH: rag_pb2.CONFIDENCE_HIGH,
}


async def scope_from_metadata(context: Any) -> TenantScope:
    md = {k.lower(): v for k, v in (context.invocation_metadata() or ())}
    try:
        return TenantScope(uuid.UUID(str(md[TENANT_KEY])), uuid.UUID(str(md[AGENT_KEY])))
    except (KeyError, ValueError):
        await context.abort(
            grpc.StatusCode.UNAUTHENTICATED, "missing or invalid tenant/agent metadata"
        )
        raise  # unreachable: abort raises


async def _abort(context: Any, exc: AppError) -> None:
    code = grpc.StatusCode.NOT_FOUND if isinstance(exc, NotFoundError) else grpc.StatusCode.INTERNAL
    await context.abort(code, exc.message)


def _u32(value: int | None) -> int:
    return max(int(value or 0), 0)


class RagServicer(rag_pb2_grpc.RagServiceServicer):
    def __init__(self, resources: Resources) -> None:
        self._r = resources

    async def Retrieve(self, request: Any, context: Any) -> Any:  # noqa: N802 - gRPC naming
        scope = await scope_from_metadata(context)
        try:
            async with self._r.sessionmaker() as session:
                knowledge = await load_agent_knowledge(session, scope)
            if request.top_k:
                from dataclasses import replace

                knowledge = replace(
                    knowledge,
                    settings=replace(knowledge.settings, top_k=min(int(request.top_k), 10)),
                )
            result, _ = await retrieve(self._r, scope, knowledge, request.question)
        except AppError as exc:
            await _abort(context, exc)
            raise
        return rag_pb2.RetrieveResponse(
            chunks=[
                rag_pb2.RetrievedChunk(
                    source_id=c.source_id,
                    file_name=c.file_name or "",
                    page=_u32(c.page),
                    section=c.section or "",
                    url=c.url or "",
                    text=c.text,
                    score=c.score,
                )
                for c in result.chunks
            ],
            confidence=_CONF[result.confidence],
            fallback=result.fallback,
        )

    async def Answer(self, request: Any, context: Any) -> AsyncIterator[Any]:  # noqa: N802
        scope = await scope_from_metadata(context)
        p = request.persona
        persona = Persona(
            agent_name=p.agent_name or _DEFAULT_PERSONA.agent_name,
            role=p.role or _DEFAULT_PERSONA.role,
            instructions=p.instructions,
            tone=p.tone or _DEFAULT_PERSONA.tone,
            response_style=p.response_style or _DEFAULT_PERSONA.response_style,
            boundaries=p.boundaries or _DEFAULT_PERSONA.boundaries,
        )
        req = AnswerRequest(
            question=request.question,
            language=request.language or None,
            persona=persona,
            history=[Turn(t.role, t.text) for t in request.conversation_history],
        )
        try:
            async for ev in AnswerService(self._r).answer_events(scope, req):
                if isinstance(ev, TokenEvent) and ev.text:
                    yield rag_pb2.AnswerChunk(token=ev.text)
                elif isinstance(ev, DoneEvent):
                    lat = ev.latency_ms
                    yield rag_pb2.AnswerChunk(
                        final=rag_pb2.AnswerFinal(
                            display_text=ev.display_text,
                            spoken_text=ev.spoken_text,
                            sources=[
                                rag_pb2.Source(
                                    file_name=s.get("file_name") or "",
                                    page=_u32(s.get("page")),
                                    section=s.get("section") or "",
                                    url=s.get("url") or "",
                                    snippet=s.get("snippet") or "",
                                    score=float(s.get("score") or 0.0),
                                )
                                for s in ev.sources
                            ],
                            confidence=_CONF[ev.confidence],
                            fallback=ev.fallback,
                            latency=rag_pb2.Latency(
                                embed_ms=lat.get("embed", 0.0),
                                search_ms=lat.get("search", 0.0),
                                rerank_ms=lat.get("rerank", 0.0),
                                llm_ttft_ms=lat.get("llm_ttft", 0.0),
                                total_ms=lat.get("total", 0.0),
                            ),
                        )
                    )
        except AppError as exc:
            await _abort(context, exc)

    async def GetKnowledgeBaseStatus(self, request: Any, context: Any) -> Any:  # noqa: N802
        from app.api.knowledge_base import status_label

        scope = await scope_from_metadata(context)
        async with self._r.sessionmaker() as session:
            kb = await repo.get_kb(session, scope)
            counts = await repo.source_counts(session, scope)
        rag_enabled = kb.rag_enabled if kb is not None else True
        status = kb.status if kb is not None else KnowledgeBaseStatus.EMPTY
        return rag_pb2.StatusResponse(
            files=counts.files,
            urls=counts.urls,
            rag_enabled=rag_enabled,
            status=status.value,
            label=status_label(counts.files, rag_enabled),
        )


def _mtls_credentials(cert: str, key: str, client_ca: str) -> Any:
    return grpc.ssl_server_credentials(
        [(Path(key).read_bytes(), Path(cert).read_bytes())],
        root_certificates=Path(client_ca).read_bytes(),
        require_client_auth=True,  # mTLS: only trusted services can set tenant metadata
    )


async def start_grpc_server(resources: Resources) -> grpc.aio.Server | None:
    s = resources.settings
    if not s.grpc_enabled:
        return None
    server = grpc.aio.server()
    rag_pb2_grpc.add_RagServiceServicer_to_server(RagServicer(resources), server)  # type: ignore[no-untyped-call]
    address = f"{s.grpc_host}:{s.grpc_port}"
    if s.grpc_tls_cert and s.grpc_tls_key and s.grpc_client_ca:
        port = server.add_secure_port(
            address, _mtls_credentials(s.grpc_tls_cert, s.grpc_tls_key, s.grpc_client_ca)
        )
    elif s.grpc_allow_insecure:
        logger.warning("gRPC listening WITHOUT TLS on %s (dev only)", address)
        port = server.add_insecure_port(address)
    else:
        logger.warning(
            "gRPC disabled: set GRPC_TLS_CERT/KEY/CLIENT_CA (or GRPC_ALLOW_INSECURE for dev)"
        )
        return None
    await server.start()
    logger.info("gRPC RagService on port %d", port)
    resources.grpc_port = port
    return server
