"""Tenant scoping of the Qdrant store, using qdrant-client's in-memory mode."""

import uuid
from collections.abc import AsyncIterator

import pytest
from qdrant_client import AsyncQdrantClient

from beai_rag_core.qdrant_store import (
    ChunkPoint,
    CollectionSpec,
    QdrantStore,
    TenantScopeViolationError,
    point_id,
)
from beai_rag_core.tenancy import TenantScope

DIM = 8


@pytest.fixture
async def store() -> AsyncIterator[QdrantStore]:
    s = QdrantStore(AsyncQdrantClient(location=":memory:"), CollectionSpec("kb_test", DIM))
    await s.ensure_collection()
    yield s
    await s.close()


def _points(source_id: uuid.UUID, n: int, version: int = 1) -> list[ChunkPoint]:
    return [
        ChunkPoint(
            id=point_id(source_id, i, version),
            dense=[0.1 * (i + 1)] * DIM,
            sparse_indices=[i, i + 1],
            sparse_values=[1.0, 0.5],
            payload={"source_id": str(source_id), "chunk_index": i, "text": f"chunk {i}"},
        )
        for i in range(n)
    ]


def test_point_id_is_deterministic() -> None:
    sid = uuid.uuid4()
    assert point_id(sid, 3, 1) == point_id(sid, 3, 1)
    assert point_id(sid, 3, 1) != point_id(sid, 3, 2)
    assert point_id(sid, 3, 1) != point_id(sid, 4, 1)


def test_scope_requires_uuids() -> None:
    with pytest.raises(TypeError):
        TenantScope(tenant_id="a", agent_id="b")  # type: ignore[arg-type]


async def test_ensure_collection_is_idempotent(store: QdrantStore) -> None:
    assert await store.ensure_collection() is False


async def test_operations_are_scoped(store: QdrantStore) -> None:
    tenant_a, tenant_b, agent = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    a = TenantScope(tenant_a, agent)
    b = TenantScope(tenant_b, agent)  # same agent id, different tenant
    a_other_agent = TenantScope(tenant_a, uuid.uuid4())
    src_a, src_b = uuid.uuid4(), uuid.uuid4()

    await store.upsert(a, _points(src_a, 3))
    await store.upsert(b, _points(src_b, 5))

    assert await store.count(a) == 3
    assert await store.count(b) == 5
    assert await store.count(a_other_agent) == 0
    # B cannot see or delete A's source even when it knows the source id.
    assert await store.count(b, source_id=src_a) == 0
    await store.delete_source(b, src_a)
    assert await store.count(a) == 3

    records = await store.scroll(a)
    assert {r.payload["tenant_id"] for r in records if r.payload} == {str(tenant_a)}

    await store.delete_source(a, src_a)
    assert await store.count(a) == 0
    assert await store.count(b) == 5


async def test_upsert_is_idempotent(store: QdrantStore) -> None:
    scope = TenantScope(uuid.uuid4(), uuid.uuid4())
    src = uuid.uuid4()
    await store.upsert(scope, _points(src, 4))
    await store.upsert(scope, _points(src, 4))
    assert await store.count(scope) == 4


async def test_payload_cannot_smuggle_other_tenant(store: QdrantStore) -> None:
    scope = TenantScope(uuid.uuid4(), uuid.uuid4())
    bad = _points(uuid.uuid4(), 1)
    bad[0].payload["tenant_id"] = str(uuid.uuid4())
    with pytest.raises(TenantScopeViolationError):
        await store.upsert(scope, bad)
