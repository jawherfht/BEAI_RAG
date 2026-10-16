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
    # Re-ranker (Qwen3-Reranker), loaded on the first /rerank call.
    rerank_model_id: str = "Qwen/Qwen3-Reranker-0.6B"
    rerank_revision: str = "e61197ed45024b0ed8a2d74b80b4d909f1255473"
    rerank_instruction: str = (
        "Given a web search query, retrieve relevant passages that answer the query"
    )
    rerank_max_length: int = 2048


class EmbedRequest(BaseModel):
    inputs: str | list[str]
    normalize: bool = True
    truncate: bool = True


class RerankRequest(BaseModel):
    query: str
    texts: list[str]
    raw_scores: bool = False


class RerankItem(BaseModel):
    index: int
    score: float


# Prompt pieces verbatim from the Qwen3-Reranker-0.6B model card.
RERANK_PREFIX = (
    "<|im_start|>system\nJudge whether the Document meets the requirements based on the Query "
    'and the Instruct provided. Note that the answer can only be "yes" or "no".<|im_end|>\n'
    "<|im_start|>user\n"
)
RERANK_SUFFIX = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"


class QwenReranker:
    """Card implementation: P("yes") from the last-token logits over {"no", "yes"}."""

    def __init__(self, model_id: str, revision: str, instruction: str, max_length: int) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self._torch = torch
        self._tok = AutoTokenizer.from_pretrained(model_id, revision=revision, padding_side="left")
        # float32 on CPU: bf16 matmuls are slow on CPUs without native bf16 support.
        self._model: Any = AutoModelForCausalLM.from_pretrained(
            model_id, revision=revision, dtype=torch.float32
        )
        self._model.eval()  # type: ignore[no-untyped-call]
        self._yes = self._tok.convert_tokens_to_ids("yes")
        self._no = self._tok.convert_tokens_to_ids("no")
        self._prefix = self._tok.encode(RERANK_PREFIX, add_special_tokens=False)
        self._suffix = self._tok.encode(RERANK_SUFFIX, add_special_tokens=False)
        self._instruction = instruction
        self._max_length = max_length

    def score(self, query: str, texts: list[str], batch_size: int = 8) -> list[float]:
        torch = self._torch
        scores: list[float] = []
        body_max = self._max_length - len(self._prefix) - len(self._suffix)
        for i in range(0, len(texts), batch_size):
            pairs = [
                f"<Instruct>: {self._instruction}\n<Query>: {query}\n<Document>: {doc}"
                for doc in texts[i : i + batch_size]
            ]
            enc = self._tok(
                pairs,
                padding=False,
                truncation="longest_first",
                return_attention_mask=False,
                max_length=body_max,
            )
            enc["input_ids"] = [self._prefix + ids + self._suffix for ids in enc["input_ids"]]
            batch = self._tok.pad(enc, padding=True, return_tensors="pt")
            with torch.no_grad():
                logits = self._model(**batch).logits[:, -1, :]
            pair = torch.stack([logits[:, self._no], logits[:, self._yes]], dim=1)
            scores.extend(torch.nn.functional.softmax(pair, dim=1)[:, 1].tolist())
        return scores


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

    @app.post("/rerank", response_model=list[RerankItem])
    async def rerank(req: RerankRequest) -> list[RerankItem]:
        if not req.texts or len(req.texts) > settings.max_batch:
            raise HTTPException(413, f"1..{settings.max_batch} texts per request")
        async with lock:
            if "reranker" not in state:
                state["reranker"] = await asyncio.to_thread(
                    QwenReranker,
                    settings.rerank_model_id,
                    settings.rerank_revision,
                    settings.rerank_instruction,
                    settings.rerank_max_length,
                )
            scores = await asyncio.to_thread(state["reranker"].score, req.query, req.texts)
        items = [RerankItem(index=i, score=s) for i, s in enumerate(scores)]
        return sorted(items, key=lambda it: it.score, reverse=True)

    return app
