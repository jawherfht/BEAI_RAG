"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import answer, health, knowledge_base, sources
from app.api.errors import install_error_handlers
from app.config import Settings, get_settings
from app.grpc_server import start_grpc_server
from app.resources import ModelOverrides, Resources
from app.telemetry.metrics import install_http_metrics


def create_app(settings: Settings | None = None, models: ModelOverrides | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level)
    logging.getLogger(__name__).info(
        "grounding thresholds %.3f / %.3f / %.3f from %s",
        settings.score_threshold,
        settings.conf_mid,
        settings.conf_high,
        settings.thresholds_source,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resources = Resources.create(settings, models)
        app.state.resources = resources
        await resources.bootstrap()
        grpc_server = await start_grpc_server(resources)
        try:
            yield
        finally:
            if grpc_server is not None:
                await grpc_server.stop(grace=5)
            await resources.close()

    app = FastAPI(
        title="BEAI Knowledge Base & RAG API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    install_error_handlers(app)
    install_http_metrics(app)
    app.include_router(health.router)
    app.include_router(knowledge_base.router)
    app.include_router(sources.router)
    app.include_router(answer.router)
    return app
