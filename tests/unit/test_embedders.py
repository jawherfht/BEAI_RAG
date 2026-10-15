import json

import httpx
import pytest

from beai_rag_core.embedding.base import EmbeddingDimensionError
from beai_rag_core.embedding.http_dense import OpenAIEmbedder, TEIEmbedder

TEMPLATE = "Instruct: find passages\nQuery: {text}"


def tei_client(seen: list[list[str]], dim: int = 4) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body["inputs"])
        assert body["normalize"] is True
        return httpx.Response(200, json=[[0.5] * dim for _ in body["inputs"]])

    return httpx.AsyncClient(base_url="http://tei", transport=httpx.MockTransport(handler))


async def test_tei_documents_have_no_instruction_and_queries_do() -> None:
    seen: list[list[str]] = []
    e = TEIEmbedder("http://tei", "m", 4, TEMPLATE, batch_size=2, client=tei_client(seen))
    await e.embed_documents(["a", "b", "c"])
    assert seen == [["a", "b"], ["c"]]  # batched
    await e.embed_queries(["what?"])
    assert seen[-1] == ["Instruct: find passages\nQuery: what?"]


async def test_dimension_mismatch_detected() -> None:
    e = TEIEmbedder("http://tei", "m", 1024, TEMPLATE, client=tei_client([], dim=768))
    with pytest.raises(EmbeddingDimensionError):
        await e.embed_documents(["x"])


async def test_openai_embedder_orders_and_normalises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [0.0, 2.0]},
                    {"index": 0, "embedding": [3.0, 4.0]},
                ]
            },
        )

    client = httpx.AsyncClient(base_url="http://vllm/v1", transport=httpx.MockTransport(handler))
    e = OpenAIEmbedder("http://vllm/v1", "m", 2, TEMPLATE, client=client)
    assert await e.embed_documents(["first", "second"]) == [[0.6, 0.8], [0.0, 1.0]]


def test_template_must_contain_text() -> None:
    with pytest.raises(ValueError):
        TEIEmbedder("http://tei", "m", 4, "no placeholder")
