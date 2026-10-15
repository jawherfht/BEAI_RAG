"""Sentence-transformers embedding server speaking TEI's ``POST /embed`` contract.

The spec's fallback when TEI cannot serve a model, and the dev server without a GPU
(``EMBED_PROVIDER=local``). Clients send exactly what they would send to TEI, so the
rag-api / worker code path is identical. Pooling and normalisation come from the model's
own sentence-transformers config (harrier: last-token pooling + L2 normalise).

    uvicorn --factory embed_server.main:create_app --port 8080
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class ServerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EMBED_SERVER_", extra="ignore")

    model_id: str = "microsoft/harrier-oss-v1-0.6b"
    revision: str = "f9b9dc8d367d443f2479d27aa5d8d2850c0774ee"
    max_batch: int = 64
    max_input_tokens: int = 8192
    threads: int | None = None


class EmbedRequest(BaseModel):
    inputs: str | list[str]
    normalize: bool = True
    truncate: bool = True


class Info(BaseModel):
    model_id: str
    revision: str
    dim: int
    max_input_length: int
    pooling: str = Field(default="from model config")


def create_app(settings: ServerSettings | None = None) -> FastAPI:
    settings = settings or ServerSettings()
    state: dict[str, Any] = {}
    lock = asyncio.Lock()  # one encode at a time; torch already uses all cores

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        import torch
        from sentence_transformers import SentenceTransformer

        if settings.threads:
            torch.set_num_threads(settings.threads)
        model = await asyncio.to_thread(
            SentenceTransformer, settings.model_id, revision=settings.revision, device="cpu"
        )
        model.max_seq_length = min(
            model.max_seq_length or settings.max_input_tokens, settings.max_input_tokens
        )
        state["model"] = model
        logger.info("loaded %s@%s", settings.model_id, settings.revision)
        yield

    app = FastAPI(title="BEAI embed server", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/info", response_model=Info)
    async def info() -> Info:
        model = state["model"]
        return Info(
            model_id=settings.model_id,
            revision=settings.revision,
            dim=int(model.get_embedding_dimension()),
            max_input_length=int(model.max_seq_length),
        )

    @app.post("/embed")
    async def embed(req: EmbedRequest) -> list[list[float]]:
        texts = [req.inputs] if isinstance(req.inputs, str) else req.inputs
        if not texts or len(texts) > settings.max_batch:
            raise HTTPException(413, f"1..{settings.max_batch} inputs per request")
        model = state["model"]
        async with lock:
            vectors = await asyncio.to_thread(
                model.encode,
                texts,
                normalize_embeddings=req.normalize,
                convert_to_numpy=True,
                batch_size=16,
            )
        return [v.tolist() for v in vectors]

    return app
