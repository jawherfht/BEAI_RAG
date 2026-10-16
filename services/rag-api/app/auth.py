"""Tenant/agent context from the API Gateway (spec sections 0.5, 7 and 9).

The tenant comes only from a verified gateway JWT or a known API key, never from the
request body or query string. An ``agent_id`` in the path that the caller may not use is
answered with 404 (not 403) so other customers' agents cannot be discovered.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

import jwt
from fastapi import Depends, Header, Path, Request, WebSocket

from app.config import Settings
from app.domain.errors import NotFoundError, UnauthorizedError
from beai_rag_core.tenancy import TenantScope


@dataclass(frozen=True, slots=True)
class AuthContext:
    tenant_id: UUID
    subject: str
    # None = the gateway did not restrict agents; data access is still scoped by tenant.
    allowed_agents: frozenset[UUID] | None

    def scope_for(self, agent_id: UUID) -> TenantScope:
        if self.allowed_agents is not None and agent_id not in self.allowed_agents:
            raise NotFoundError("Agent not found")
        return TenantScope(tenant_id=self.tenant_id, agent_id=agent_id)


def _parse_uuid(value: object, what: str) -> UUID:
    try:
        return UUID(str(value))
    except (ValueError, TypeError) as exc:
        raise UnauthorizedError(f"Invalid {what} in credentials") from exc


def _parse_agents(value: object) -> frozenset[UUID] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise UnauthorizedError("Invalid agents claim in credentials")
    return frozenset(_parse_uuid(a, "agent id") for a in value)


def context_from_jwt(token: str, settings: Settings) -> AuthContext:
    key: str | None = None
    if any(a.startswith("HS") for a in settings.jwt_algorithms):
        key = settings.jwt_secret.get_secret_value() if settings.jwt_secret else None
    elif settings.jwt_public_key is not None:
        key = settings.jwt_public_key.get_secret_value()
    if not key:
        raise UnauthorizedError("JWT authentication is not configured")
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            key,
            algorithms=settings.jwt_algorithms,
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={
                "require": ["exp", settings.jwt_tenant_claim],
                "verify_aud": settings.jwt_audience is not None,
            },
        )
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Invalid or expired token") from exc
    return AuthContext(
        tenant_id=_parse_uuid(claims[settings.jwt_tenant_claim], "tenant id"),
        subject=str(claims.get("sub", "")),
        allowed_agents=_parse_agents(claims.get(settings.jwt_agents_claim)),
    )


def context_from_api_key(api_key: str, settings: Settings) -> AuthContext:
    if settings.api_keys is None:
        raise UnauthorizedError("Invalid API key")
    try:
        registry: dict[str, dict[str, Any]] = json.loads(settings.api_keys.get_secret_value())
    except json.JSONDecodeError as exc:
        raise UnauthorizedError("API key authentication is misconfigured") from exc
    digest = hashlib.sha256(api_key.encode()).hexdigest()
    match: dict[str, Any] | None = None
    for known, entry in registry.items():
        if hmac.compare_digest(known, digest):
            match = entry
    if match is None:
        raise UnauthorizedError("Invalid API key")
    return AuthContext(
        tenant_id=_parse_uuid(match.get("tenant_id"), "tenant id"),
        subject=f"api-key:{digest[:12]}",
        allowed_agents=_parse_agents(match.get("agents")),
    )


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


async def get_auth_context(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    authorization: Annotated[str | None, Header()] = None,
    x_api_key: Annotated[str | None, Header()] = None,
) -> AuthContext:
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise UnauthorizedError("Authorization header must be 'Bearer <token>'")
        return context_from_jwt(token.strip(), settings)
    if x_api_key:
        return context_from_api_key(x_api_key, settings)
    raise UnauthorizedError("Missing credentials")


async def get_agent_scope(
    auth: Annotated[AuthContext, Depends(get_auth_context)],
    agent_id: Annotated[str, Path()],
) -> TenantScope:
    """Scope for routes under /v1/agents/{agent_id}/... . Malformed ids are 404, too."""
    try:
        parsed = UUID(agent_id)
    except ValueError as exc:
        raise NotFoundError("Agent not found") from exc
    return auth.scope_for(parsed)


AuthDep = Annotated[AuthContext, Depends(get_auth_context)]
AgentScopeDep = Annotated[TenantScope, Depends(get_agent_scope)]


def scope_from_websocket(websocket: WebSocket, agent_id: str, settings: Settings) -> TenantScope:
    """WebSocket auth: ``Authorization: Bearer`` / ``X-API-Key`` headers, or the
    ``access_token`` query parameter (browsers cannot set headers on a WebSocket)."""
    authorization = websocket.headers.get("authorization")
    token = websocket.query_params.get("access_token")
    if authorization:
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() != "bearer" or not value:
            raise UnauthorizedError("Authorization header must be 'Bearer <token>'")
        ctx = context_from_jwt(value.strip(), settings)
    elif token:
        ctx = context_from_jwt(token, settings)
    elif api_key := websocket.headers.get("x-api-key"):
        ctx = context_from_api_key(api_key, settings)
    else:
        raise UnauthorizedError("Missing credentials")
    try:
        parsed = UUID(agent_id)
    except ValueError as exc:
        raise NotFoundError("Agent not found") from exc
    return ctx.scope_for(parsed)
