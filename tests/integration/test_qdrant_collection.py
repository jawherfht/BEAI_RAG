"""Phase 1: the kb_chunks collection has the vectors and payload indexes from spec 4.2."""

import uuid

import httpx
import pytest
from qdrant_client import models as qm

from beai_rag_core.qdrant_store import ChunkPoint, CollectionSpec, QdrantStore, point_id
from beai_rag_core.tenancy import TenantScope
from tests.integration.conftest import QDRANT_API_KEY, Infra


@pytest.fixture
async def store(infra: Infra) -> QdrantStore:
    return QdrantStore.connect(
        infra.qdrant_url, QDRANT_API_KEY, CollectionSpec(f"kb_it_{uuid.uuid4().hex[:8]}", 1024)
    )


def test_qdrant_requires_api_key(infra: Infra) -> None:
    assert httpx.get(f"{infra.qdrant_url}/collections").status_code == 401


async def test_collection_config(store: QdrantStore) -> None:
    assert await store.ensure_collection() is True
    assert await store.ensure_collection() is False  # idempotent
    info = await store.collection_info()
    params = info.config.params

    assert isinstance(params.vectors, dict)
    dense = params.vectors["dense"]
    assert dense.size == 1024
    assert dense.distance == qm.Distance.COSINE
    assert dense.on_disk is True
    assert dense.hnsw_config is not None
    assert (dense.hnsw_config.m, dense.hnsw_config.ef_construct) == (16, 100)
    quant = dense.quantization_config
    assert isinstance(quant, qm.ScalarQuantization)
    assert quant.scalar.type == qm.ScalarType.INT8
    assert quant.scalar.always_ram is True

    assert params.sparse_vectors is not None
    assert params.sparse_vectors["sparse"].modifier == qm.Modifier.IDF

    schema = info.payload_schema
    assert set(schema) == {"tenant_id", "agent_id", "source_id", "lang"}
    for name, idx in schema.items():
        assert idx.data_type == qm.PayloadSchemaType.KEYWORD
        assert isinstance(idx.params, qm.KeywordIndexParams)
        assert bool(idx.params.is_tenant) is (name == "tenant_id")
    await store.close()


async def test_scoped_roundtrip_on_real_qdrant(store: QdrantStore) -> None:
    await store.ensure_collection()
    a = TenantScope(uuid.uuid4(), uuid.uuid4())
    b = TenantScope(uuid.uuid4(), a.agent_id)
    src = uuid.uuid4()
    pts = [
        ChunkPoint(
            id=point_id(src, i, 1),
            dense=[0.01 * (i + 1)] * 1024,
            sparse_indices=[1, 7],
            sparse_values=[0.3, 0.9],
            payload={"source_id": str(src), "file_name": "returns-policy.pdf", "page": 2},
        )
        for i in range(3)
    ]
    await store.upsert(a, pts)
    assert await store.count(a) == 3
    assert await store.count(b) == 0
    await store.delete_source(a, src)
    assert await store.count(a) == 0
    await store.close()
