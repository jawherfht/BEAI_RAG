from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.errors import install_error_handlers


def _client() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internals")

    @app.get("/typed/{n}")
    async def typed(n: int) -> dict[str, int]:
        return {"n": n}

    return TestClient(app, raise_server_exceptions=False)


def test_unknown_route_uses_error_shape() -> None:
    r = _client().get("/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_validation_error_shape() -> None:
    r = _client().get("/typed/abc")
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "validation_error"
    assert body["details"]["errors"]


def test_unhandled_error_hides_internals() -> None:
    r = _client().get("/boom")
    assert r.status_code == 500
    assert r.json() == {
        "error": {"code": "internal_error", "message": "Internal error", "details": {}}
    }
