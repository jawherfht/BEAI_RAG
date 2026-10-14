"""Phase 1 acceptance check (spec section 15).

Starts rag-api against the running docker-compose stack (`make up` first), prints /readyz
and the Qdrant collection config, then stops the API. Exits non-zero if anything is not OK.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "services/rag-api"
PORT = int(os.environ.get("PHASE1_PORT", "8765"))


def main() -> int:
    env = {**os.environ, "PYTHONPATH": str(API_DIR)}
    api = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "uvicorn", "--factory", "app.main:create_app", "--port", str(PORT)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        base = f"http://127.0.0.1:{PORT}"
        for _ in range(60):
            try:
                if httpx.get(f"{base}/healthz", timeout=1).status_code == 200:
                    break
            except httpx.TransportError:
                time.sleep(0.5)
        else:
            print("rag-api did not start")
            return 1
        ready = httpx.get(f"{base}/readyz", timeout=10)
        print(f"GET /readyz -> {ready.status_code}")
        print(json.dumps(ready.json(), indent=2))
    finally:
        api.terminate()
        api.wait(timeout=10)

    print("\nQdrant collection config:")
    show = subprocess.run(
        [sys.executable, "-m", "app.bootstrap", "--show"], cwd=API_DIR, env=env, check=False
    )
    return 0 if ready.status_code == 200 and show.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
