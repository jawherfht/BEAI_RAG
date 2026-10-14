"""Re-export of the shared Qdrant store.

The implementation lives in ``beai_rag_core.qdrant_store`` so the ingestion worker uses the
same tenant-scoped code path (see docs/decisions/0002-shared-core-package.md).
"""

from beai_rag_core.qdrant_store import (
    DENSE_VECTOR,
    PAYLOAD_INDEXES,
    SPARSE_VECTOR,
    ChunkPoint,
    CollectionSpec,
    QdrantStore,
    TenantScopeViolationError,
    point_id,
    scope_filter,
)
from beai_rag_core.tenancy import TenantScope

__all__ = [
    "DENSE_VECTOR",
    "PAYLOAD_INDEXES",
    "SPARSE_VECTOR",
    "ChunkPoint",
    "CollectionSpec",
    "QdrantStore",
    "TenantScope",
    "TenantScopeViolationError",
    "point_id",
    "scope_filter",
]
