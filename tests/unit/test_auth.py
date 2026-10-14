"""Auth context: tenant only from credentials; foreign agents are 404, never 403."""

import hashlib
import json
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.errors import install_error_handlers
from app.auth import AgentScopeDep, AuthDep
from tests.helpers import make_settings, make_token

TENANT = uuid.uuid4()
AGENT = uuid.uuid4()
OTHER_AGENT = uuid.uuid4()
API_KEY = "beai_test_key_123"


def _app(**settings_overrides: object) -> TestClient:
    app = FastAPI()
    app.state.settings = make_settings(**settings_overrides)
    install_error_handlers(app)

    @app.get("/v1/whoami")
    async def whoami(auth: AuthDep) -> dict[str, str]:
        return {"tenant_id": str(auth.tenant_id)}

    @app.post("/v1/agents/{agent_id}/probe")
    async def probe(scope: AgentScopeDep, body: dict[str, str] | None = None) -> dict[str, str]:
        return {"tenant_id": str(scope.tenant_id), "agent_id": str(scope.agent_id)}

    return TestClient(app)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_missing_credentials_is_401_with_error_shape() -> None:
    r = _app().get("/v1/whoami")
    assert r.status_code == 401
    assert r.json() == {
        "error": {"code": "unauthorized", "message": "Missing credentials", "details": {}}
    }


def test_valid_jwt_gives_tenant() -> None:
    r = _app().get("/v1/whoami", headers=_bearer(make_token(TENANT)))
    assert r.status_code == 200
    assert r.json() == {"tenant_id": str(TENANT)}


@pytest.mark.parametrize(
    "token",
    [
        make_token(TENANT, secret="wrong-secret-wrong-secret-wrong-secret"),
        make_token(TENANT, exp_in_s=-10),
        make_token("not-a-uuid"),
        "garbage",
    ],
)
def test_invalid_jwt_is_401(token: str) -> None:
    assert _app().get("/v1/whoami", headers=_bearer(token)).status_code == 401


def test_non_bearer_scheme_is_401() -> None:
    r = _app().get("/v1/whoami", headers={"Authorization": "Basic abc"})
    assert r.status_code == 401


def test_body_cannot_override_tenant() -> None:
    other_tenant = str(uuid.uuid4())
    r = _app().post(
        f"/v1/agents/{AGENT}/probe",
        headers=_bearer(make_token(TENANT)),
        json={"tenant_id": other_tenant, "agent_id": str(OTHER_AGENT)},
    )
    assert r.status_code == 200
    assert r.json() == {"tenant_id": str(TENANT), "agent_id": str(AGENT)}


def test_agent_not_allowed_is_404() -> None:
    client = _app()
    token = make_token(TENANT, agents=[AGENT])
    assert client.post(f"/v1/agents/{AGENT}/probe", headers=_bearer(token)).status_code == 200
    r = client.post(f"/v1/agents/{OTHER_AGENT}/probe", headers=_bearer(token))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_malformed_agent_id_is_404_not_422() -> None:
    r = _app().post("/v1/agents/not-a-uuid/probe", headers=_bearer(make_token(TENANT)))
    assert r.status_code == 404


def test_api_key_auth() -> None:
    registry = {
        hashlib.sha256(API_KEY.encode()).hexdigest(): {
            "tenant_id": str(TENANT),
            "agents": [str(AGENT)],
        }
    }
    client = _app(api_keys=json.dumps(registry))
    ok = client.post(f"/v1/agents/{AGENT}/probe", headers={"X-API-Key": API_KEY})
    assert ok.status_code == 200
    assert ok.json()["tenant_id"] == str(TENANT)
    assert client.get("/v1/whoami", headers={"X-API-Key": "wrong"}).status_code == 401
    foreign = client.post(f"/v1/agents/{OTHER_AGENT}/probe", headers={"X-API-Key": API_KEY})
    assert foreign.status_code == 404


def test_jwt_not_configured_is_401() -> None:
    client = _app(jwt_algorithms=["RS256"], jwt_secret=None, jwt_public_key=None)
    assert client.get("/v1/whoami", headers=_bearer(make_token(TENANT))).status_code == 401
