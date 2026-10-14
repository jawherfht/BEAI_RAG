"""Tenant scope: the only way to address tenant data (spec sections 0.5 and 9).

A ``TenantScope`` is built exclusively from the authenticated context (gateway JWT,
API key or gRPC metadata from a trusted caller), never from a request body.
"""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TenantScope:
    tenant_id: UUID
    agent_id: UUID

    def __post_init__(self) -> None:
        # Guard against callers passing strings straight from user input.
        if not isinstance(self.tenant_id, UUID) or not isinstance(self.agent_id, UUID):
            raise TypeError("TenantScope requires UUID tenant_id and agent_id")
