"""Tenant isolation suite (spec section 9) — mandatory and blocking.

Tenants A and B ingest near-identical documents (same file names, same text except for the
numbers). Every query from A, through retrieval and the cache, must only ever return A's
points; including when A and B use the SAME agent id, and when B knows A's source ids.
"""

import asyncio
import uuid

from app.services.retrieval import load_agent_knowledge, retrieve
from beai_rag_core.tenancy import TenantScope
from tests.integration.conftest import Tenant, new_tenant, running_api, running_worker
from tests.integration.test_ingestion_pipeline import upload, wait_status

DOC_A = (
    b"Acme returns policy. Returns are accepted within 30 days, unworn, with receipt. "
    b"Tenant A secret code ALPHA-111."
)
DOC_B = (
    b"Acme returns policy. Returns are accepted within 60 days, unworn, with receipt. "
    b"Tenant B secret code BRAVO-222."
)
QUESTIONS = [
    "What's your return policy?",
    "returns accepted days receipt",
    "secret code",
    "BRAVO-222",
    "ALPHA-111",
]


async def test_tenants_never_see_each_other(migrated) -> None:  # type: ignore[no-untyped-def]
    a = new_tenant()
    b_same_agent = Tenant(uuid.uuid4(), a.agent_id)
    b_other = new_tenant()
    async with running_api(migrated) as api, running_worker(api):
        sa = await upload(api, a, "returns-policy.txt", DOC_A, "text/plain")
        sb1 = await upload(api, b_same_agent, "returns-policy.txt", DOC_B, "text/plain")
        sb2 = await upload(api, b_other, "returns-policy.txt", DOC_B, "text/plain")
        await asyncio.gather(
            wait_status(api, a, sa, "ready"),
            wait_status(api, b_same_agent, sb1, "ready"),
            wait_status(api, b_other, sb2, "ready"),
        )
        r = api.resources
        for tenant, own_source, forbidden in [
            (a, sa, "BRAVO-222"),
            (b_same_agent, sb1, "ALPHA-111"),
            (b_other, sb2, "ALPHA-111"),
        ]:
            scope = TenantScope(tenant.tenant_id, tenant.agent_id)
            async with r.sessionmaker() as session:
                knowledge = await load_agent_knowledge(session, scope)
            for q in QUESTIONS:
                for attempt in ("miss", "hit"):  # second call is served from the cache
                    result, cache_hit = await retrieve(r, scope, knowledge, q)
                    assert cache_hit is (attempt == "hit")
                    for c in result.chunks + result.candidates:
                        assert c.source_id == own_source, (tenant, q, attempt)
                        assert forbidden not in c.text, (tenant, q, attempt)

        # Raw store access with A's scope never sees B, even with B's source id.
        scope_a = TenantScope(a.tenant_id, a.agent_id)
        assert await r.store.count(scope_a, source_id=uuid.UUID(sb1)) == 0
        assert {(p.payload or {})["source_id"] for p in await r.store.scroll(scope_a)} == {sa}


async def test_cache_is_scoped_and_invalidated_by_kb_version(migrated) -> None:  # type: ignore[no-untyped-def]
    a = new_tenant()
    async with running_api(migrated) as api, running_worker(api):
        sa = await upload(api, a, "a.txt", DOC_A, "text/plain")
        await wait_status(api, a, sa, "ready")
        r = api.resources
        scope = TenantScope(a.tenant_id, a.agent_id)
        async with r.sessionmaker() as session:
            k1 = await load_agent_knowledge(session, scope)
        _, hit = await retrieve(r, scope, k1, "What's your return policy?")
        assert not hit
        _, hit = await retrieve(r, scope, k1, "  what's your RETURN policy ")
        assert hit
        # Any settings change bumps kb_version -> the cached entry is no longer used.
        await api.client.put(f"{a.base}/knowledge-base", headers=a.headers, json={"top_k": 3})
        async with r.sessionmaker() as session:
            k2 = await load_agent_knowledge(session, scope)
        assert k2.kb_version > k1.kb_version
        result, hit = await retrieve(r, scope, k2, "What's your return policy?")
        assert not hit and len(result.candidates) <= 3
