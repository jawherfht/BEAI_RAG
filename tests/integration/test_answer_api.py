"""Phase 4 endpoints against real Qdrant/Postgres/Redis/RabbitMQ with a scripted LLM double:
/test JSON, /answer SSE, WS /ws, cache, fallback without LLM, LLM failure, usage events,
answers_log, and endpoint-level tenant isolation."""

import asyncio
import json
import uuid

import aio_pika
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.generation.llm import LLMUnavailableError
from app.main import create_app
from beai_rag_core.db.models import AnswerLog
from beai_rag_core.queue import USAGE_QUEUE
from tests.fakes import ScriptedLLM
from tests.helpers import make_token
from tests.integration.conftest import (
    Api,
    Infra,
    Tenant,
    api_settings,
    fake_models,
    new_tenant,
    running_api,
    running_worker,
)
from tests.integration.test_ingestion_pipeline import upload, wait_status

POLICY = (
    "Acme returns policy.\n\nSection 4 Returns. Returns are accepted within 30 days, unworn, "
    "with receipt. Items must keep all tags attached.\n\nSection 5 Refunds. Refunds are paid "
    "within 5 business days to the original payment method."
)
FALLBACK = "I'm not sure about that. Would you like me to connect you with someone?"
# Grounded question for the hashing test embedder (bag of words: needs shared words).
Q = "Can I return items within 30 days with a receipt?"
Q_VARIANT = "  can i return items within 30 days with a receipt "


async def ingest(api: Api, t: Tenant, text: str = POLICY, name: str = "returns-policy.txt") -> str:
    sid = await upload(api, t, name, text.encode(), "text/plain")
    await wait_status(api, t, sid, "ready")
    return sid


async def test_test_endpoint_grounded_answer_with_sources(migrated: Infra) -> None:
    t = new_tenant()
    llm = ScriptedLLM()
    async with running_api(migrated, llm=llm) as api, running_worker(api):
        await ingest(api, t)
        r = await api.client.post(
            f"{t.base}/test",
            headers=t.headers,
            json={
                "question": Q,
                "persona": {"agent_name": "Acme Shoes", "tone": "warm"},
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert (
            body["answer"]
            == "Returns are accepted within 30 days, unworn, with receipt — see Section 4."
        )
        assert body["spoken_text"] == body["answer"]
        assert body["fallback"] is False and body["confidence"] in {"high", "medium"}
        assert [s["file_name"] for s in body["sources"]] == ["returns-policy.txt"]
        assert body["sources"][0]["page"] == 1 and len(body["sources"][0]["snippet"]) <= 200
        assert {"embed", "search", "llm_ttft", "llm_total", "total"} <= set(body["latency_ms"])
        system, user = llm.calls[0][0]["content"], llm.calls[0][-1]["content"]
        assert system.startswith("You are the voice of Acme Shoes.") and "tone: warm" in system
        assert "[1] (returns-policy.txt, p.1" in user and user.endswith(f"QUESTION: {Q}")

        # Same question again -> answer cache, the LLM is not called again.
        again = (
            await api.client.post(f"{t.base}/test", headers=t.headers, json={"question": Q_VARIANT})
        ).json()
        assert len(llm.calls) == 2  # persona differs from the first call -> different cache entry
        third = (
            await api.client.post(f"{t.base}/test", headers=t.headers, json={"question": Q})
        ).json()
        assert third["cache_hit"] is True and len(llm.calls) == 2
        assert third["answer"] == again["answer"] and third["sources"] == again["sources"]


async def test_unanswerable_returns_fallback_without_calling_llm(migrated: Infra) -> None:
    t = new_tenant()
    llm = ScriptedLLM()
    async with running_api(migrated, llm=llm) as api, running_worker(api):
        await ingest(api, t)
        r = (
            await api.client.post(
                f"{t.base}/test",
                headers=t.headers,
                json={"question": "Who won the 1998 football world cup?"},
            )
        ).json()
        assert r["fallback"] is True and r["confidence"] == "low" and r["sources"] == []
        assert r["answer"] == FALLBACK
        assert llm.calls == []


async def test_llm_reply_with_fallback_sentence_is_marked_fallback(migrated: Infra) -> None:
    t = new_tenant()
    llm = ScriptedLLM(lambda m: FALLBACK)
    async with running_api(migrated, llm=llm) as api, running_worker(api):
        await ingest(api, t)
        r = (
            await api.client.post(
                f"{t.base}/test",
                headers=t.headers,
                json={"question": "Can I return items after 30 days with receipt?"},
            )
        ).json()
        assert len(llm.calls) == 1
        assert r["fallback"] is True and r["confidence"] == "low" and r["sources"] == []


async def test_answer_without_citation_is_not_high(migrated: Infra) -> None:
    t = new_tenant()
    async with (
        running_api(migrated, llm=ScriptedLLM(lambda m: "Thirty days with a receipt.")) as api,
        running_worker(api),
    ):
        await ingest(api, t)
        r = (
            await api.client.post(
                f"{t.base}/test",
                headers=t.headers,
                json={"question": "returns accepted within 30 days unworn receipt"},
            )
        ).json()
        assert r["fallback"] is False and r["sources"] == [] and r["confidence"] != "high"


async def test_llm_unavailable_degrades_to_fallback_and_is_not_cached(migrated: Infra) -> None:
    t = new_tenant()
    llm = ScriptedLLM(fail=LLMUnavailableError("429 after retries"))
    async with running_api(migrated, llm=llm) as api, running_worker(api):
        await ingest(api, t)
        for _ in range(2):
            r = (
                await api.client.post(
                    f"{t.base}/test",
                    headers=t.headers,
                    json={"question": Q},
                )
            ).json()
            assert (
                r["fallback"] is True
                and r["error"] == "llm_unavailable"
                and r["cache_hit"] is False
            )
        assert len(llm.calls) == 2


async def test_sse_stream_events(migrated: Infra) -> None:
    t = new_tenant()
    async with running_api(migrated) as api, running_worker(api):
        await ingest(api, t)
        async with api.client.stream(
            "POST",
            f"{t.base}/answer",
            headers=t.headers,
            json={"question": Q},
        ) as resp:
            assert resp.status_code == 200 and resp.headers["content-type"].startswith(
                "text/event-stream"
            )
            events = []
            name = None
            async for line in resp.aiter_lines():
                if line.startswith("event: "):
                    name = line[7:]
                elif line.startswith("data: "):
                    events.append((name, json.loads(line[6:])))
        names = [n for n, _ in events]
        assert names[-2:] == ["sources", "done"] and set(names[:-2]) == {"token"}
        display = "".join(d["text"] for n, d in events if n == "token")
        spoken = "".join(d["spoken"] for n, d in events if n == "token")
        assert "[1]" in display and "[1]" not in spoken
        done = events[-1][1]
        assert done["sources"][0]["file_name"] == "returns-policy.txt" and done["fallback"] is False


async def test_sse_unknown_agent_is_404_before_streaming(migrated: Infra) -> None:
    t = new_tenant()  # no knowledge base yet
    async with running_api(migrated) as api:
        r = await api.client.post(f"{t.base}/answer", headers=t.headers, json={"question": "hi"})
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


async def test_usage_event_and_sampled_answer_log(migrated: Infra) -> None:
    t = new_tenant()
    async with running_api(migrated, answer_log_sample_rate=1.0) as api, running_worker(api):
        await ingest(api, t)
        await api.client.post(
            f"{t.base}/test",
            headers=t.headers,
            json={"question": f"{Q} jane@example.com"},
        )
        await asyncio.sleep(0.5)  # side effects run in the background
        async with api.resources.sessionmaker() as session:
            logs = (
                (await session.execute(select(AnswerLog).where(AnswerLog.tenant_id == t.tenant_id)))
                .scalars()
                .all()
            )
        assert len(logs) == 1 and "[email]" in logs[0].question and "jane@" not in logs[0].question
    connection = await aio_pika.connect(migrated.rabbitmq_url)
    async with connection:
        queue = await (await connection.channel()).declare_queue(USAGE_QUEUE, durable=True)
        events = []
        while (msg := await queue.get(no_ack=True, fail=False)) is not None:
            events.append(json.loads(msg.body))
    mine = [e for e in events if e["tenant_id"] == str(t.tenant_id)]
    assert len(mine) == 1 and mine[0]["tokens_in"] == 321 and mine[0]["rerank_used"] is False


async def test_endpoint_isolation_including_cache(migrated: Infra) -> None:
    a = new_tenant()
    b = Tenant(uuid.uuid4(), a.agent_id)  # same agent id, other tenant
    async with running_api(migrated) as api, running_worker(api):
        await ingest(api, a, POLICY + " Secret code ALPHA-111.", "a-policy.txt")
        await ingest(
            api, b, POLICY.replace("30 days", "60 days") + " Secret code BRAVO-222.", "b-policy.txt"
        )
        for _ in range(2):  # second round is served from the cache
            ra = (
                await api.client.post(
                    f"{a.base}/test",
                    headers=a.headers,
                    json={"question": Q},
                )
            ).json()
            rb = (
                await api.client.post(
                    f"{b.base}/test",
                    headers=b.headers,
                    json={"question": Q},
                )
            ).json()
            assert {s["file_name"] for s in ra["sources"]} == {"a-policy.txt"}
            assert {s["file_name"] for s in rb["sources"]} == {"b-policy.txt"}
            assert all("BRAVO" not in s["snippet"] for s in ra["sources"])


def test_websocket_flow_and_auth(migrated: Infra) -> None:
    t = new_tenant()
    settings = api_settings(migrated)
    app = create_app(settings, fake_models(settings))

    async def seed() -> None:
        async with running_api(migrated) as api, running_worker(api):
            await ingest(api, t)

    asyncio.run(seed())
    with TestClient(app) as client:
        token = make_token(t.tenant_id, [t.agent_id])
        with client.websocket_connect(f"{t.base}/ws?access_token={token}") as ws:
            ws.send_text(json.dumps({"question": Q}))
            msgs = []
            while True:
                msg = ws.receive_json()
                msgs.append(msg)
                if msg["type"] == "done":
                    break
            assert msgs[-1]["sources"][0]["file_name"] == "returns-policy.txt"
            ws.send_text(json.dumps({"question": ""}))
            assert ws.receive_json()["type"] == "error"
        other_agent = f"/v1/agents/{uuid.uuid4()}/ws?access_token={token}"
        try:
            with client.websocket_connect(other_agent) as ws:
                ws.receive_json()
            raise AssertionError("expected close")
        except Exception as exc:  # starlette raises WebSocketDisconnect with the close code
            assert getattr(exc, "code", None) == 4404
