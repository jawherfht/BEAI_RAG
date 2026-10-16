"""Phase 1 acceptance: /readyz shows every dependency OK; a broken one gives 503."""

from fastapi.testclient import TestClient

from app.main import create_app
from tests.helpers import make_settings
from tests.integration.conftest import Infra, fake_models


def _client(infra: Infra, **overrides: object) -> TestClient:
    values: dict[str, object] = {
        **infra.settings_overrides(),
        "qdrant_auto_create": True,
        "s3_auto_create_bucket": True,
        "readiness_timeout_s": 3.0,
        **overrides,
    }
    settings = make_settings(**values)
    return TestClient(create_app(settings, fake_models(settings)))


def test_healthz(migrated: Infra) -> None:
    with _client(migrated) as client:
        assert client.get("/healthz").json() == {"status": "ok"}


def test_readyz_all_ok(migrated: Infra) -> None:
    with _client(migrated) as client:
        r = client.get("/readyz")
        body = r.json()
        assert r.status_code == 200, body
        assert body["status"] == "ok"
        assert set(body["checks"]) == {
            "embedder",
            "qdrant",
            "postgres",
            "redis",
            "rabbitmq",
            "object_storage",
        }
        assert all(c["ok"] for c in body["checks"].values())


def test_readyz_reports_broken_dependency(migrated: Infra) -> None:
    with _client(migrated, redis_url="redis://127.0.0.1:1/0") as client:
        r = client.get("/readyz")
        body = r.json()
        assert r.status_code == 503
        assert body["checks"]["redis"]["ok"] is False
        assert "error" in body["checks"]["redis"]
        assert body["checks"]["qdrant"]["ok"] is True


def test_metrics_exposed(migrated: Infra) -> None:
    with _client(migrated) as client:
        client.get("/healthz")
        r = client.get("/metrics")
        assert r.status_code == 200
        assert "http_request_duration_seconds" in r.text
