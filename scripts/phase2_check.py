"""Phase 2 acceptance check (spec section 15) with the REAL models.

Needs `make up`, an embedding server at EMBED_URL (TEI, `docker compose --profile gpu|cpu-models
up -d`), and Hugging Face access for Docling's PDF models, the BM25 model and the tokenizer.

Steps: start rag-api and the ingestion worker in-process; upload
eval/datasets/kb1_retail/returns-policy.pdf; wait for `ready` (< 2 min); print the Qdrant
payloads (file_name, page, section, tenant_id, agent_id); delete the source; confirm that
all its points are gone.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path

import httpx
import jwt

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "services/rag-api"), str(ROOT / "services/ingestion-worker")]

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from beai_rag_core.tenancy import TenantScope  # noqa: E402
from worker.config import WorkerSettings  # noqa: E402
from worker.main import run as run_worker  # noqa: E402

PDF = (
    Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "eval/datasets/kb1_retail/returns-policy.pdf"
)
CHECK_RETURNS_PAGE = PDF.name == "returns-policy.pdf"
READY_BUDGET_S = 120


async def main() -> int:
    settings = Settings()
    if settings.jwt_secret is None:
        print("JWT_SECRET must be set in .env for this local check")
        return 1
    tenant, agent = uuid.uuid4(), uuid.uuid4()
    token = jwt.encode(
        {"tenant_id": str(tenant), "agents": [str(agent)], "exp": int(time.time()) + 3600},
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    headers = {"Authorization": f"Bearer {token}"}
    base = f"/v1/agents/{agent}"
    scope = TenantScope(tenant, agent)

    worker = asyncio.create_task(run_worker(WorkerSettings()))
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://api") as client:
            started = time.monotonic()
            r = await client.post(
                f"{base}/sources/files",
                headers=headers,
                files=[("files", (PDF.name, PDF.read_bytes(), "application/pdf"))],
            )
            print(f"POST /sources/files -> {r.status_code} {r.json()}")
            sid = r.json()[0]["source_id"]
            status = "queued"
            # Keep waiting past the budget so slow runs still report their real duration.
            while time.monotonic() - started < 5 * READY_BUDGET_S and status not in {
                "ready",
                "error",
            }:
                await asyncio.sleep(1)
                if worker.done():
                    worker.result()  # surface worker start-up errors
                sources = (await client.get(f"{base}/sources", headers=headers)).json()
                src = next(s for s in sources if s["id"] == sid)
                if src["status"] != status:
                    status = src["status"]
                    print(f"  {time.monotonic() - started:6.1f}s  status={status}")
            elapsed = time.monotonic() - started
            print(json.dumps(src, indent=2, default=str))
            if status != "ready":
                print(f"FAIL: status {status} after {elapsed:.1f}s: {src.get('error')}")
                return 1
            print(f"ready in {elapsed:.1f}s (budget {READY_BUDGET_S}s)")

            store = app.state.resources.store
            records = await store.scroll(scope, source_id=uuid.UUID(sid), limit=1000)
            print(f"\n{len(records)} Qdrant points; payload excerpt:")
            for rec in sorted(records, key=lambda r: (r.payload or {}).get("chunk_index", 0))[:12]:
                p = rec.payload or {}
                print(
                    json.dumps(
                        {
                            k: p.get(k)
                            for k in (
                                "file_name",
                                "page",
                                "page_end",
                                "section",
                                "tenant_id",
                                "agent_id",
                                "lang",
                            )
                        }
                        | {"text": str(p.get("text", ""))[:70]},
                        ensure_ascii=False,
                    )
                )
            hit = [
                r
                for r in records
                if "30 days, unworn, with receipt" in str((r.payload or {}).get("text"))
            ]
            ok_payload = (bool(hit) and (hit[0].payload or {}).get("page") == 2) or (
                not CHECK_RETURNS_PAGE
                and all((r.payload or {}).get("file_name") == PDF.name for r in records)
            )

            d = await client.delete(f"{base}/sources/{sid}", headers=headers)
            print(f"\nDELETE /sources/{sid} -> {d.status_code}")
            for _ in range(60):
                await asyncio.sleep(1)
                if await store.count(scope, source_id=uuid.UUID(sid)) == 0:
                    break
            remaining = await store.count(scope, source_id=uuid.UUID(sid))
            print(f"points remaining for the source: {remaining}")
    worker.cancel()
    passed = elapsed < READY_BUDGET_S and ok_payload and remaining == 0
    print("\nPHASE 2 ACCEPTANCE:", "PASS" if passed else "FAIL")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
