"""Contract test (spec section 13): docs/openapi.json matches the app. Run `make openapi`."""

import json
from pathlib import Path

from app.config import Settings
from app.main import create_app

SNAPSHOT = Path(__file__).resolve().parents[2] / "docs/openapi.json"


def test_openapi_snapshot_is_current() -> None:
    app = create_app(
        Settings(_env_file=None, environment="test", jwt_algorithms=["RS256"], grpc_enabled=False)
    )
    assert json.loads(SNAPSHOT.read_text()) == json.loads(json.dumps(app.openapi())), (
        "OpenAPI schema changed: run `make openapi` and commit docs/openapi.json"
    )
