"""In-process harness for acceptance/eval scripts: rag-api + ingestion worker + a test tenant.

Uses the real configuration (.env): Qdrant, Postgres, RabbitMQ, S3, the embedding server at
EMBED_URL, FastEmbed BM25, Docling. Nothing here is a test double.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import jwt

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "services/rag-api"), str(ROOT / "services/ingestion-worker")]

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.resources import Resources  # noqa: E402
from beai_rag_core.tenancy import TenantScope  # noqa: E402
from worker.config import WorkerSettings  # noqa: E402
from worker.main import run as run_worker  # noqa: E402

MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".html": "text/html",
}


@dataclass
class Session:
    client: httpx.AsyncClient
    resources: Resources
    scope: TenantScope
    headers: dict[str, str]

    @property
    def base(self) -> str:
        return f"/v1/agents/{self.scope.agent_id}"

    async def upload(self, paths: list[Path]) -> list[str]:
        files = [("files", (p.name, p.read_bytes(), MIME[p.suffix])) for p in paths]
        r = await self.client.post(f"{self.base}/sources/files", headers=self.headers, files=files)
        r.raise_for_status()
        return [str(x["source_id"]) for x in r.json()]

    async def wait_ready(self, timeout_s: float = 1800) -> list[dict[str, Any]]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            sources = (await self.client.get(f"{self.base}/sources", headers=self.headers)).json()
            if sources and all(s["status"] in {"ready", "error"} for s in sources):
                return list(sources)
            await asyncio.sleep(1)
        raise TimeoutError("sources not ready")

    async def put_settings(self, **settings: Any) -> dict[str, Any]:
        r = await self.client.put(
            f"{self.base}/knowledge-base", headers=self.headers, json=settings
        )
        r.raise_for_status()
        return dict(r.json())


@contextlib.asynccontextmanager
async def session(
    *, with_worker: bool = True, settings: Settings | None = None
) -> AsyncIterator[Session]:
    settings = settings or Settings()
    if settings.jwt_secret is None:
        raise SystemExit("JWT_SECRET must be set in .env for local eval runs")
    scope = TenantScope(uuid.uuid4(), uuid.uuid4())
    token = jwt.encode(
        {
            "tenant_id": str(scope.tenant_id),
            "agents": [str(scope.agent_id)],
            "exp": int(time.time()) + 86400,
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    worker = asyncio.create_task(run_worker(WorkerSettings())) if with_worker else None
    app = create_app(settings)
    try:
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://api", timeout=600
            ) as client:
                yield Session(
                    client, app.state.resources, scope, {"Authorization": f"Bearer {token}"}
                )
    finally:
        if worker is not None:
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await worker


def percentile(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    k = (len(ordered) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)
