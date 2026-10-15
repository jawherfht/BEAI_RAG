"""Source endpoints against real Postgres, S3 and RabbitMQ (no worker running)."""

import io
import zipfile

import pytest

from beai_rag_core.enums import JobKind
from beai_rag_core.queue import parse_job
from beai_rag_core.storage import source_object_key
from beai_rag_core.tenancy import TenantScope
from tests.integration.conftest import Infra, drain_queue, new_tenant, running_api


def docx_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<w:document/>")
    return buf.getvalue()


async def test_upload_returns_202_stores_file_and_queues_job(migrated: Infra) -> None:
    t = new_tenant()
    await drain_queue(migrated.rabbitmq_url, JobKind.INDEX)
    async with running_api(migrated) as api:
        r = await api.client.post(
            f"{t.base}/sources/files",
            headers=t.headers,
            files=[
                ("files", ("returns-policy.txt", b"30 days, unworn, with receipt.", "text/plain")),
                ("files", ("guide.docx", docx_bytes(), "application/octet-stream")),
            ],
        )
        assert r.status_code == 202, r.text
        body = r.json()
        assert [b["file_name"] for b in body] == ["returns-policy.txt", "guide.docx"]
        assert all(b["status"] == "queued" and not b["duplicate"] for b in body)

        scope = TenantScope(t.tenant_id, t.agent_id)
        key = source_object_key(
            scope, __import__("uuid").UUID(body[0]["source_id"]), "returns-policy.txt"
        )
        assert key.startswith(f"tenants/{t.tenant_id}/agents/{t.agent_id}/sources/")
        assert await api.resources.storage.get(key) == b"30 days, unworn, with receipt."

        sources = (await api.client.get(f"{t.base}/sources", headers=t.headers)).json()
        assert {s["mime_type"] for s in sources} == {
            "text/plain",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }
        kb = (await api.client.get(f"{t.base}/knowledge-base", headers=t.headers)).json()
        assert kb["status"] == "indexing" and kb["counts"]["files"] == 2

    jobs = [parse_job(m.body) for m in await drain_queue(migrated.rabbitmq_url, JobKind.INDEX)]
    assert {str(j.source_id) for j in jobs} == {b["source_id"] for b in body}
    assert all(j.tenant_id == t.tenant_id and j.agent_id == t.agent_id for j in jobs)


async def test_duplicate_upload_is_deduplicated(migrated: Infra) -> None:
    t = new_tenant()
    async with running_api(migrated) as api:
        first = await api.client.post(
            f"{t.base}/sources/files",
            headers=t.headers,
            files=[("files", ("a.txt", b"same bytes", "text/plain"))],
        )
        again = await api.client.post(
            f"{t.base}/sources/files",
            headers=t.headers,
            files=[("files", ("renamed.txt", b"same bytes", "text/plain"))],
        )
        assert again.status_code == 202
        assert again.json()[0]["duplicate"] is True
        assert again.json()[0]["source_id"] == first.json()[0]["source_id"]
        assert len((await api.client.get(f"{t.base}/sources", headers=t.headers)).json()) == 1
    await drain_queue(migrated.rabbitmq_url, JobKind.INDEX)


@pytest.mark.parametrize(
    ("name", "data", "status", "code"),
    [
        ("photo.png", b"\x89PNG\r\n\x1a\n", 415, "unsupported_media_type"),
        ("fake.pdf", b"hello", 415, "unsupported_media_type"),
    ],
)
async def test_bad_uploads_rejected_and_nothing_written(
    migrated: Infra, name: str, data: bytes, status: int, code: str
) -> None:
    t = new_tenant()
    async with running_api(migrated) as api:
        r = await api.client.post(
            f"{t.base}/sources/files",
            headers=t.headers,
            files=[("files", ("ok.txt", b"fine", "text/plain")), ("files", (name, data, "x/y"))],
        )
        assert r.status_code == status
        assert r.json()["error"]["code"] == code
        assert (await api.client.get(f"{t.base}/sources", headers=t.headers)).json() == []


async def test_size_limit(migrated: Infra) -> None:
    t = new_tenant()
    async with running_api(migrated, max_upload_mb=1) as api:
        r = await api.client.post(
            f"{t.base}/sources/files",
            headers=t.headers,
            files=[("files", ("big.txt", b"a" * (1024 * 1024 + 1), "text/plain"))],
        )
        assert r.status_code == 413


async def test_other_tenant_cannot_see_or_touch_sources(migrated: Infra) -> None:
    a, b = new_tenant(), new_tenant()
    async with running_api(migrated) as api:
        r = await api.client.post(
            f"{a.base}/sources/files",
            headers=a.headers,
            files=[("files", ("a.txt", b"tenant A secret", "text/plain"))],
        )
        sid = r.json()[0]["source_id"]
        # B uses its own token but A's agent id: 404 (agent not in B's allowed agents).
        assert (await api.client.get(f"{a.base}/sources", headers=b.headers)).status_code == 404
        # B on its own agent with A's source id: 404.
        assert (
            await api.client.delete(f"{b.base}/sources/{sid}", headers=b.headers)
        ).status_code == 404
        assert (
            await api.client.post(f"{b.base}/sources/{sid}/reindex", headers=b.headers)
        ).status_code == 404
        # Same agent id, other tenant (no agents claim): still isolated by tenant_id.
        from tests.helpers import make_token

        b_same_agent = {"Authorization": f"Bearer {make_token(b.tenant_id)}"}
        assert (await api.client.get(f"{a.base}/sources", headers=b_same_agent)).json() == []
    await drain_queue(migrated.rabbitmq_url, JobKind.INDEX)


async def test_url_source_and_validation(migrated: Infra) -> None:
    t = new_tenant()
    async with running_api(migrated) as api:
        ok = await api.client.post(
            f"{t.base}/sources/urls",
            headers=t.headers,
            json={"url": "https://example.com/help", "crawl_depth": 2, "max_pages": 10},
        )
        assert ok.status_code == 202 and ok.json()["url"] == "https://example.com/help"
        dup = await api.client.post(
            f"{t.base}/sources/urls", headers=t.headers, json={"url": "https://example.com/help"}
        )
        assert dup.json()["duplicate"] is True
        for bad in [
            {"url": "http://127.0.0.1/admin"},
            {"url": "http://localhost/"},
            {"url": "ftp://example.com"},
            {"url": "https://example.com", "crawl_depth": 4},
            {"url": "https://example.com", "max_pages": 501},
        ]:
            r = await api.client.post(f"{t.base}/sources/urls", headers=t.headers, json=bad)
            assert r.status_code == 422, bad
    await drain_queue(migrated.rabbitmq_url, JobKind.INDEX)


async def test_business_info_upsert(migrated: Infra) -> None:
    t = new_tenant()
    form = {
        "company_name": "Acme",
        "hours": "9-5",
        "faq": [{"question": "Ship?", "answer": "Yes."}],
    }
    async with running_api(migrated) as api:
        r1 = await api.client.put(f"{t.base}/sources/business-info", headers=t.headers, json=form)
        r2 = await api.client.put(
            f"{t.base}/sources/business-info", headers=t.headers, json={**form, "hours": "8-6"}
        )
        assert r1.status_code == r2.status_code == 202
        assert r1.json()["source_id"] == r2.json()["source_id"]
        assert r1.json()["file_name"] == "Business info"
        sources = (await api.client.get(f"{t.base}/sources", headers=t.headers)).json()
        assert len(sources) == 1 and sources[0]["type"] == "business_info"
        empty = await api.client.put(f"{t.base}/sources/business-info", headers=t.headers, json={})
        assert empty.status_code == 422
    await drain_queue(migrated.rabbitmq_url, JobKind.INDEX)


async def test_settings_put_and_chunk_size_change_queues_reindex(migrated: Infra) -> None:
    t = new_tenant()
    async with running_api(migrated) as api:
        default = (await api.client.get(f"{t.base}/knowledge-base", headers=t.headers)).json()
        assert (default["chunk_size"], default["chunk_overlap"], default["top_k"]) == (512, 64, 4)
        await api.client.post(
            f"{t.base}/sources/files",
            headers=t.headers,
            files=[
                ("files", ("a.txt", b"alpha", "text/plain")),
                ("files", ("b.txt", b"beta", "text/plain")),
            ],
        )
        await drain_queue(migrated.rabbitmq_url, JobKind.INDEX)
        before = (await api.client.get(f"{t.base}/knowledge-base", headers=t.headers)).json()[
            "kb_version"
        ]

        r = await api.client.put(f"{t.base}/knowledge-base", headers=t.headers, json={"top_k": 6})
        assert r.json()["top_k"] == 6 and r.json()["reindexing"] is False
        assert r.json()["kb_version"] == before + 1
        assert await drain_queue(migrated.rabbitmq_url, JobKind.REINDEX) == []

        r = await api.client.put(
            f"{t.base}/knowledge-base", headers=t.headers, json={"chunk_size": 800}
        )
        body = r.json()
        assert (body["chunk_size"], body["chunk_overlap"], body["reindexing"]) == (800, 100, True)
        reindex = [
            parse_job(m.body) for m in await drain_queue(migrated.rabbitmq_url, JobKind.REINDEX)
        ]
        assert len(reindex) == 2 and all(j.agent_id == t.agent_id for j in reindex)

        for bad in [{"chunk_size": 525}, {"top_k": 11}, {"tenant_id": "x"}]:
            assert (
                await api.client.put(f"{t.base}/knowledge-base", headers=t.headers, json=bad)
            ).status_code == 422


async def test_status_label_for_persona_builder(migrated: Infra) -> None:
    t = new_tenant()
    async with running_api(migrated) as api:
        files = [("files", (f"f{i}.txt", f"file {i}".encode(), "text/plain")) for i in range(3)]
        await api.client.post(f"{t.base}/sources/files", headers=t.headers, files=files)
        for u in ["https://example.com/a", "https://example.com/b"]:
            await api.client.post(f"{t.base}/sources/urls", headers=t.headers, json={"url": u})
        s = (await api.client.get(f"{t.base}/knowledge-base/status", headers=t.headers)).json()
        assert s == {
            "files": 3,
            "urls": 2,
            "rag_enabled": True,
            "status": "indexing",
            "label": "Knowledge base: 3 files, RAG on",
        }
    await drain_queue(migrated.rabbitmq_url, JobKind.INDEX)


async def test_delete_marks_deleting_and_queues_job(migrated: Infra) -> None:
    t = new_tenant()
    async with running_api(migrated) as api:
        r = await api.client.post(
            f"{t.base}/sources/files",
            headers=t.headers,
            files=[("files", ("a.txt", b"x y z", "text/plain"))],
        )
        sid = r.json()[0]["source_id"]
        d = await api.client.delete(f"{t.base}/sources/{sid}", headers=t.headers)
        assert d.status_code == 202 and d.json()["status"] == "deleting"
        again = await api.client.delete(f"{t.base}/sources/{sid}", headers=t.headers)
        assert again.status_code == 202
        assert (
            await api.client.post(f"{t.base}/sources/{sid}/reindex", headers=t.headers)
        ).status_code == 409
    jobs = await drain_queue(migrated.rabbitmq_url, JobKind.DELETE)
    assert [str(parse_job(m.body).source_id) for m in jobs] == [sid]
    await drain_queue(migrated.rabbitmq_url, JobKind.INDEX)
