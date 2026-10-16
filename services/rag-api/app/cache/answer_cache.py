"""Redis answer cache (spec sections 6 step 1 and 9).

Key = sha256(tenant_id | agent_id | kb_version | normalized question). Any content or settings
change bumps kb_version, so stale entries are never read; they expire after the TTL (24 h).
The key always includes the tenant and agent, so a hit can never cross tenants.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

from redis.asyncio import Redis

from beai_rag_core.tenancy import TenantScope

KEY_PREFIX = "beai:rag:"
_SPACES = re.compile(r"\s+")
_TRAILING = re.compile(r"[\s?!.¿¡؟。！？]+$")


def normalize_question(question: str) -> str:
    q = unicodedata.normalize("NFKC", question).casefold()
    q = _SPACES.sub(" ", q).strip()
    return _TRAILING.sub("", q)


def cache_key(scope: TenantScope, kb_version: int, question: str, kind: str = "answer") -> str:
    """``kind`` separates what is cached ("answer" in Phase 4, "retrieval" in Phase 3)."""
    raw = f"{scope.tenant_id}|{scope.agent_id}|{kb_version}|{normalize_question(question)}"
    return f"{KEY_PREFIX}{kind}:{hashlib.sha256(raw.encode()).hexdigest()}"


class AnswerCache:
    def __init__(self, redis: Redis, ttl_s: int, kind: str = "answer") -> None:
        self._redis = redis
        self._ttl = ttl_s
        self._kind = kind

    async def get(
        self, scope: TenantScope, kb_version: int, question: str
    ) -> dict[str, Any] | None:
        raw = await self._redis.get(cache_key(scope, kb_version, question, self._kind))
        if raw is None:
            return None
        value: dict[str, Any] = json.loads(raw)
        return value

    async def set(
        self, scope: TenantScope, kb_version: int, question: str, value: dict[str, Any]
    ) -> None:
        await self._redis.set(
            cache_key(scope, kb_version, question, self._kind),
            json.dumps(value, ensure_ascii=False),
            ex=self._ttl,
        )
