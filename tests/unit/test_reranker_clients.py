import json

import httpx

from app.retrieval.reranker import CARD_PREFIX, CARD_SUFFIX, LocalReranker, VllmReranker


async def test_local_reranker_maps_scores_back_to_input_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body == {"query": "q", "texts": ["a", "b", "c"]}
        return httpx.Response(
            200,
            json=[
                {"index": 2, "score": 0.9},
                {"index": 0, "score": 0.5},
                {"index": 1, "score": 0.1},
            ],
        )

    r = LocalReranker(
        "http://x",
        client=httpx.AsyncClient(base_url="http://x", transport=httpx.MockTransport(handler)),
    )
    assert await r.rerank("q", ["a", "b", "c"]) == [0.5, 0.1, 0.9]
    assert await r.rerank("q", []) == []


async def test_vllm_reranker_uses_card_template() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.7}]})

    r = VllmReranker(
        "http://v",
        "Qwen/Qwen3-Reranker-0.6B",
        instruction="Find answers",
        client=httpx.AsyncClient(base_url="http://v", transport=httpx.MockTransport(handler)),
    )
    assert await r.rerank("What is X?", ["X is Y."]) == [0.7]
    assert seen["query"] == f"{CARD_PREFIX}<Instruct>: Find answers\n<Query>: What is X?\n"
    assert seen["documents"] == [f"<Document>: X is Y.{CARD_SUFFIX}"]
