"""Test helpers shared by unit and integration tests."""

import time
import uuid
from typing import Any

import jwt

from app.config import Settings

TEST_JWT_SECRET = "test-secret-at-least-32-bytes-long-xx"


def make_settings(**overrides: Any) -> Settings:
    base: dict[str, Any] = {
        "environment": "test",
        "jwt_algorithms": ["HS256"],
        "jwt_secret": TEST_JWT_SECRET,
        "qdrant_auto_create": False,
        "s3_auto_create_bucket": False,
        "readiness_timeout_s": 0.5,
        "grpc_enabled": False,
        "thresholds_file": "/nonexistent/thresholds.json",  # hermetic: no calibrated file
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)


def make_token(
    tenant_id: uuid.UUID | str,
    agents: list[uuid.UUID] | None = None,
    *,
    secret: str = TEST_JWT_SECRET,
    exp_in_s: int = 300,
    **extra: Any,
) -> str:
    claims: dict[str, Any] = {
        "sub": "user-1",
        "tenant_id": str(tenant_id),
        "exp": int(time.time()) + exp_in_s,
        **extra,
    }
    if agents is not None:
        claims["agents"] = [str(a) for a in agents]
    return jwt.encode(claims, secret, algorithm="HS256")
