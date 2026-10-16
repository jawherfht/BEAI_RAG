"""Prometheus metrics (spec section 10): HTTP latency, RAG stage latency, answer counters."""

import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from prometheus_client import Counter, Histogram

HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route", "status"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.8, 1.0, 2.5, 5.0),
)


RAG_STAGE = Histogram(
    "rag_stage_seconds",
    "Latency of each live RAG stage",
    ["stage"],  # embed, search, rerank, llm_ttft, llm_total, total
    buckets=(0.005, 0.01, 0.02, 0.03, 0.06, 0.1, 0.2, 0.3, 0.5, 0.8, 1.2, 2.0, 5.0, 10.0),
)
ANSWERS_TOTAL = Counter("answers_total", "Answers by confidence", ["confidence"])
FALLBACK_TOTAL = Counter("fallback_total", "Answers that used the fallback message", ["reason"])
ANSWER_CACHE_HITS = Counter("answer_cache_hits_total", "Answers served from the cache")
LLM_ERRORS = Counter("llm_errors_total", "LLM calls that failed after retries")


def observe_latency(latency_ms: dict[str, float]) -> None:
    for stage, ms in latency_ms.items():
        if ms:
            RAG_STAGE.labels(stage).observe(ms / 1000)


def install_http_metrics(app: FastAPI) -> None:
    @app.middleware("http")
    async def _record(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            route = request.scope.get("route")
            path = getattr(route, "path", "unmatched")
            HTTP_LATENCY.labels(request.method, path, str(status)).observe(
                time.perf_counter() - start
            )
