#!/usr/bin/env bash
# Start rag-api (:8000), the ingestion worker and the CPU embed-server (:8080) in the background
# against the compose infrastructure (`make up` first). Logs: .stack-logs/. Stop: scripts/dev-stack.sh stop
set -euo pipefail
cd "$(dirname "$0")/.."
LOGS="$(pwd)/.stack-logs"
mkdir -p "$LOGS"

stop() {
  for f in "$LOGS"/*.pid; do
    [ -f "$f" ] || continue
    kill "$(cat "$f")" 2>/dev/null || true
    rm -f "$f"
  done
}

if [ "${1:-start}" = "stop" ]; then stop; exit 0; fi

start() {  # name, workdir, command...
  local name=$1 dir=$2; shift 2
  (cd "$dir" && nohup "$@" >"$LOGS/$name.log" 2>&1 & echo $! >"$LOGS/$name.pid")
}

curl -sf localhost:8080/health >/dev/null 2>&1 || start embed-server services/embed-server ../../.venv/bin/uvicorn --factory embed_server.main:create_app --port 8080
curl -sf localhost:8000/healthz >/dev/null 2>&1 || start rag-api services/rag-api ../../.venv/bin/uvicorn --factory app.main:create_app --port 8000
start worker services/ingestion-worker ../../.venv/bin/python -m worker.main

for url in localhost:8080/health localhost:8000/healthz; do
  for _ in $(seq 1 120); do curl -sf "$url" >/dev/null && break; sleep 1; done
done
echo "stack up: rag-api :8000, embed-server :8080, worker (logs in $LOGS/)"
