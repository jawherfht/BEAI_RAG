"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import health, knowledge_base, sources
from app.api.errors import install_error_handlers
from app.config import Settings, get_settings
from app.resources import Resources
from app.telemetry.metrics import install_http_metrics


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(level=settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resources = Resources.create(settings)
        app.state.resources = resources
        await resources.bootstrap()
        try:
            yield
        finally:
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
    return app
