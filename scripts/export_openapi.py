"""Write the OpenAPI schema of rag-api to docs/openapi.json (no running services needed)."""

import json
from pathlib import Path

from app.config import Settings
from app.main import create_app

OUT = Path(__file__).resolve().parents[1] / "docs/openapi.json"


def main() -> None:
    app = create_app(
        Settings(_env_file=None, environment="test", jwt_algorithms=["RS256"], grpc_enabled=False)
    )
    OUT.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
