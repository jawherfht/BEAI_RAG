"""The single gateway to Qdrant (spec sections 4.2 and 9).

Every read, count, write and delete on tenant data goes through ``QdrantStore`` and
requires a ``TenantScope``. The scope filter (``tenant_id`` AND ``agent_id``) is added
here and nowhere else. No other module may call the Qdrant client directly; this is
enforced by ``tests/unit/test_no_raw_qdrant_calls.py``.

Collection-level administration (create collection, payload indexes, read the config)
needs no scope because it never touches tenant data.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from qdrant_client import AsyncQdrantClient
from qdrant_client import models as qm

from beai_rag_core.tenancy import TenantScope

DENSE_VECTOR = "dense"
SPARSE_VECTOR = "sparse"

# Namespace for deterministic point ids: uuid5(namespace, "source:chunk:version").
POINT_ID_NAMESPACE = uuid.UUID("6f1d3c2e-8a4b-5e7f-9c0d-1a2b3c4d5e6f")

# Payload indexes that must exist before the first upsert.
PAYLOAD_INDEXES: tuple[str, ...] = ("tenant_id", "agent_id", "source_id", "lang")


def point_id(source_id: UUID, chunk_index: int, source_kb_version: int) -> UUID:
    """Deterministic point id so ingestion retries are idempotent."""
    return uuid.uuid5(POINT_ID_NAMESPACE, f"{source_id}:{chunk_index}:{source_kb_version}")


@dataclass(frozen=True, slots=True)
class CollectionSpec:
    name: str
    dense_dim: int
    hnsw_m: int = 16
    hnsw_ef_construct: int = 100
    # Tiered multitenancy: large tenants can later be moved to a dedicated shard
    # by setting a custom shard key; kept as config so it is not a rewrite.
    shard_number: int | None = None
    replication_factor: int | None = None


@dataclass(slots=True)
class ChunkPoint:
    """A point to upsert. ``payload`` must not contain tenant/agent ids; the store adds them."""

    id: UUID
    dense: Sequence[float]
    sparse_indices: Sequence[int]
    sparse_values: Sequence[float]
    payload: dict[str, Any] = field(default_factory=dict)


class TenantScopeViolationError(ValueError):
    """Raised when a payload tries to set tenant/agent ids that differ from the scope."""


def scope_filter(scope: TenantScope, extra: Sequence[qm.Condition] = ()) -> qm.Filter:
    """The mandatory tenant + agent filter, optionally AND-ed with extra conditions."""
    must: list[qm.Condition] = [
        qm.FieldCondition(key="tenant_id", match=qm.MatchValue(value=str(scope.tenant_id))),
        qm.FieldCondition(key="agent_id", match=qm.MatchValue(value=str(scope.agent_id))),
        *extra,
    ]
    return qm.Filter(must=must)


class QdrantStore:
    def __init__(self, client: AsyncQdrantClient, spec: CollectionSpec) -> None:
        self._client = client
        self._spec = spec

    @classmethod
    def connect(
        cls, url: str, api_key: str | None, spec: CollectionSpec, timeout_s: float = 5.0
    ) -> QdrantStore:
        client = AsyncQdrantClient(url=url, api_key=api_key, timeout=int(max(1, timeout_s)))
        return cls(client, spec)

    @property
    def collection(self) -> str:
        return self._spec.name

    async def close(self) -> None:
        await self._client.close()

    # ---- administration (no tenant data) -------------------------------------------

    async def ping(self) -> bool:
        await self._client.get_collections()
        return True

    async def ensure_collection(self) -> bool:
        """Create the collection and payload indexes if missing. Returns True if created."""
        created = False
        if not await self._client.collection_exists(self._spec.name):
            await self._client.create_collection(
                collection_name=self._spec.name,
                vectors_config={
                    DENSE_VECTOR: qm.VectorParams(
                        size=self._spec.dense_dim,
                        distance=qm.Distance.COSINE,
                        on_disk=True,  # originals on disk, used for rescoring
                        hnsw_config=qm.HnswConfigDiff(
                            m=self._spec.hnsw_m, ef_construct=self._spec.hnsw_ef_construct
                        ),
                        quantization_config=qm.ScalarQuantization(
                            scalar=qm.ScalarQuantizationConfig(
                                type=qm.ScalarType.INT8, quantile=0.99, always_ram=True
                            )
                        ),
                    )
                },
                sparse_vectors_config={
                    SPARSE_VECTOR: qm.SparseVectorParams(modifier=qm.Modifier.IDF)
                },
                hnsw_config=qm.HnswConfigDiff(
                    m=self._spec.hnsw_m, ef_construct=self._spec.hnsw_ef_construct
                ),
                shard_number=self._spec.shard_number,
                replication_factor=self._spec.replication_factor,
            )
            created = True
        await self._ensure_payload_indexes()
        return created

    async def _ensure_payload_indexes(self) -> None:
        info = await self._client.get_collection(self._spec.name)
        existing = set((info.payload_schema or {}).keys())
        for name in PAYLOAD_INDEXES:
            if name in existing:
                continue
            schema: qm.KeywordIndexParams = qm.KeywordIndexParams(
                type=qm.KeywordIndexType.KEYWORD, is_tenant=(name == "tenant_id")
            )
            await self._client.create_payload_index(
                collection_name=self._spec.name, field_name=name, field_schema=schema, wait=True
            )

    async def collection_info(self) -> qm.CollectionInfo:
        return await self._client.get_collection(self._spec.name)

    # ---- tenant-scoped operations --------------------------------------------------

    async def upsert(self, scope: TenantScope, points: Sequence[ChunkPoint]) -> None:
        if not points:
            return
        structs: list[qm.PointStruct] = []
        for p in points:
            for key in ("tenant_id", "agent_id"):
                if key in p.payload and str(p.payload[key]) != str(getattr(scope, key)):
                    raise TenantScopeViolationError(f"payload {key} does not match scope")
            payload = {
                **p.payload,
                "tenant_id": str(scope.tenant_id),
                "agent_id": str(scope.agent_id),
            }
            structs.append(
                qm.PointStruct(
                    id=str(p.id),
                    vector={
                        DENSE_VECTOR: list(p.dense),
                        SPARSE_VECTOR: qm.SparseVector(
                            indices=list(p.sparse_indices), values=list(p.sparse_values)
                        ),
                    },
                    payload=payload,
                )
            )
        await self._client.upsert(collection_name=self._spec.name, points=structs, wait=True)

    async def count(self, scope: TenantScope, source_id: UUID | None = None) -> int:
        result = await self._client.count(
            collection_name=self._spec.name,
            count_filter=scope_filter(scope, self._source_condition(source_id)),
            exact=True,
        )
        return result.count

    async def scroll(
        self, scope: TenantScope, source_id: UUID | None = None, limit: int = 100
    ) -> list[qm.Record]:
        records, _ = await self._client.scroll(
            collection_name=self._spec.name,
            scroll_filter=scope_filter(scope, self._source_condition(source_id)),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return records

    async def delete_source(self, scope: TenantScope, source_id: UUID) -> None:
        await self._client.delete(
            collection_name=self._spec.name,
            points_selector=qm.FilterSelector(
                filter=scope_filter(scope, self._source_condition(source_id))
            ),
            wait=True,
        )

    @staticmethod
    def _source_condition(source_id: UUID | None) -> list[qm.Condition]:
        if source_id is None:
            return []
        return [qm.FieldCondition(key="source_id", match=qm.MatchValue(value=str(source_id)))]
