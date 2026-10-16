"""gRPC RagService: Retrieve, streaming Answer, status, metadata auth and isolation."""

import grpc
import pytest

from app.grpc_gen.beai.rag.v1 import rag_pb2, rag_pb2_grpc
from tests.integration.conftest import Infra, new_tenant, running_api, running_worker
from tests.integration.test_answer_api import POLICY, Q, ingest

GRPC = {"grpc_enabled": True, "grpc_allow_insecure": True, "grpc_host": "127.0.0.1", "grpc_port": 0}


def md(t) -> list[tuple[str, str]]:  # type: ignore[no-untyped-def]
    return [("x-beai-tenant-id", str(t.tenant_id)), ("x-beai-agent-id", str(t.agent_id))]


async def test_grpc_retrieve_answer_status(migrated: Infra) -> None:
    t, other = new_tenant(), new_tenant()
    async with running_api(migrated, **GRPC) as api, running_worker(api):
        await ingest(api, t)
        port = api.resources.grpc_port
        assert port
        async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
            stub = rag_pb2_grpc.RagServiceStub(channel)  # type: ignore[no-untyped-call]

            r = await stub.Retrieve(rag_pb2.RetrieveRequest(question=Q, top_k=2), metadata=md(t))
            assert not r.fallback and r.chunks and r.chunks[0].file_name == "returns-policy.txt"
            assert r.chunks[0].page == 1 and r.confidence != rag_pb2.CONFIDENCE_UNSPECIFIED

            tokens, final = [], None
            async for chunk in stub.Answer(
                rag_pb2.AnswerRequest(question=Q, persona=rag_pb2.Persona(agent_name="Acme")),
                metadata=md(t),
            ):
                if chunk.HasField("token"):
                    tokens.append(chunk.token)
                else:
                    final = chunk.final
            assert tokens and final is not None
            assert final.sources[0].file_name == "returns-policy.txt" and not final.fallback
            assert "[1]" not in final.spoken_text and final.latency.total_ms > 0

            s = await stub.GetKnowledgeBaseStatus(rag_pb2.StatusRequest(), metadata=md(t))
            assert (s.files, s.urls, s.rag_enabled, s.status) == (1, 0, True, "ready")
            assert s.label == "Knowledge base: 1 file, RAG on"

            # Another tenant's metadata sees nothing of t's knowledge base.
            with pytest.raises(grpc.aio.AioRpcError) as err:
                await stub.Retrieve(rag_pb2.RetrieveRequest(question=Q), metadata=md(other))
            assert err.value.code() == grpc.StatusCode.NOT_FOUND

            with pytest.raises(grpc.aio.AioRpcError) as err:
                await stub.Retrieve(rag_pb2.RetrieveRequest(question=Q))
            assert err.value.code() == grpc.StatusCode.UNAUTHENTICATED
    assert POLICY


async def test_grpc_not_started_without_tls_or_dev_flag(migrated: Infra) -> None:
    async with running_api(migrated, grpc_enabled=True, grpc_port=0) as api:
        assert api.resources.grpc_port is None
