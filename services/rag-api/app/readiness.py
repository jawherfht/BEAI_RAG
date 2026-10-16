"""Readiness checks for /readyz. Each check runs concurrently with a timeout."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text

from app.resources import Resources

Check = Callable[[Resources], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class CheckResult:
    ok: bool
    latency_ms: float
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"ok": self.ok, "latency_ms": round(self.latency_ms, 1)}
        if self.error:
            out["error"] = self.error
        return out


async def check_qdrant(r: Resources) -> None:
    info = await r.store.collection_info()  # raises if Qdrant is down or collection missing
    if info.config.params.vectors is None:
        raise RuntimeError("collection has no vectors config")


async def check_postgres(r: Resources) -> None:
    async with r.engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def check_redis(r: Resources) -> None:
    await r.redis.ping()


async def check_rabbitmq(r: Resources) -> None:
    await r.publisher.ping()


async def check_object_storage(r: Resources) -> None:
    await r.storage.ping()


async def check_embedder(r: Resources) -> None:
    await r.dense.ping()


async def check_reranker(r: Resources) -> None:
    if r.reranker is None:
        raise RuntimeError("re-ranker is not configured")
    await r.reranker.ping()


async def check_llm(r: Resources) -> None:
    await r.llm.ping()


CHECKS: dict[str, Check] = {
    "embedder": check_embedder,
    "qdrant": check_qdrant,
    "postgres": check_postgres,
    "redis": check_redis,
    "rabbitmq": check_rabbitmq,
    "object_storage": check_object_storage,
}


async def _run(name: str, check: Check, r: Resources) -> tuple[str, CheckResult]:
    start = time.perf_counter()
    try:
        await asyncio.wait_for(check(r), timeout=r.settings.readiness_timeout_s)
    except Exception as exc:  # report, never raise
        msg = f"{type(exc).__name__}: {exc}"[:300] or type(exc).__name__
        return name, CheckResult(False, (time.perf_counter() - start) * 1000, msg)
    return name, CheckResult(True, (time.perf_counter() - start) * 1000)


async def run_checks(
    r: Resources, checks: dict[str, Check] | None = None
) -> dict[str, CheckResult]:
    selected = checks if checks is not None else dict(CHECKS)
    if checks is None and r.settings.readiness_check_reranker:
        selected["reranker"] = check_reranker
    if checks is None and r.settings.readiness_check_llm:
        selected["llm"] = check_llm
    results = await asyncio.gather(*(_run(n, c, r) for n, c in selected.items()))
    return dict(results)
