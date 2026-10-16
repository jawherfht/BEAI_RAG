"""OpenAI-compatible client: SSE parsing, thinking switch, 429 backoff, no auth header."""

import json

import httpx
import pytest

from app.generation.llm import LLMUnavailableError, OpenAICompatibleClient, parse_duration_s


def sse(*chunks: dict | str) -> bytes:  # type: ignore[type-arg]
    lines = [f"data: {c if isinstance(c, str) else json.dumps(c)}\n\n" for c in chunks]
    return "".join(lines).encode()


def delta(text: str) -> dict:  # type: ignore[type-arg]
    return {"choices": [{"delta": {"content": text}}]}


def client(handler, **kw) -> OpenAICompatibleClient:  # type: ignore[no-untyped-def]
    http = httpx.AsyncClient(base_url="http://llm/v1", transport=httpx.MockTransport(handler))
    return OpenAICompatibleClient(
        "http://llm/v1", "qwen/qwen3.8-27b", client=http, retry_base_s=0.01, **kw
    )


async def collect(c: OpenAICompatibleClient) -> tuple[str, list]:  # type: ignore[type-arg]
    tokens, usage = [], []
    async for ev in c.stream([{"role": "user", "content": "hi"}], max_tokens=50, temperature=0.2):
        if ev.token:
            tokens.append(ev.token)
        if ev.usage:
            usage.append(ev.usage)
    return "".join(tokens), usage


@pytest.mark.parametrize(
    ("value", "seconds"),
    [
        ("2", 2.0),
        ("517ms", 0.517),
        ("2m52.8s", 172.8),
        ("1h2m", 3720.0),
        ("1.5s", 1.5),
        (None, None),
        ("soon", None),
    ],
)
def test_parse_duration(value: str | None, seconds: float | None) -> None:
    got = parse_duration_s(value)
    assert got == pytest.approx(seconds) if seconds is not None else got is None


async def test_streams_tokens_and_usage_with_vllm_switch() -> None:
    seen: dict = {}  # type: ignore[type-arg]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        seen["auth"] = request.headers.get("authorization")
        body = sse(
            delta("30 "),
            delta("days [1]."),
            {"choices": [], "usage": {"prompt_tokens": 900, "completion_tokens": 12}},
            "[DONE]",
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    text, usage = await collect(client(handler))
    assert text == "30 days [1]." and usage[0].prompt_tokens == 900
    assert (
        seen["chat_template_kwargs"] == {"enable_thinking": False}
        and "reasoning_effort" not in seen
    )
    assert seen["stream"] is True and seen["temperature"] == 0.2 and seen["max_tokens"] == 50
    assert seen["auth"] is None  # no key configured -> the proxy/gateway adds it


async def test_groq_switch_and_x_groq_usage() -> None:
    seen: dict = {}  # type: ignore[type-arg]

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        body = sse(
            delta("ok"),
            {
                "choices": [{"delta": {}}],
                "x_groq": {"usage": {"prompt_tokens": 5, "completion_tokens": 1}},
            },
            "[DONE]",
        )
        return httpx.Response(200, content=body)

    text, usage = await collect(client(handler, thinking_switch="reasoning_effort"))
    assert text == "ok" and usage[0].completion_tokens == 1
    assert seen["reasoning_effort"] == "none" and "chat_template_kwargs" not in seen


async def test_think_block_is_removed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=sse(
                delta("<thi"),
                delta("nk>plan..."),
                delta("</think>\n\nAnswer"),
                delta(" here."),
                "[DONE]",
            ),
        )

    assert (await collect(client(handler)))[0] == "Answer here."


async def test_retries_429_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(
                429, json={"error": "rate limited"}, headers={"retry-after": "0.01"}
            )
        return httpx.Response(200, content=sse(delta("fine"), "[DONE]"))

    assert (await collect(client(handler)))[0] == "fine" and calls["n"] == 3


async def test_gives_up_after_max_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429, json={"error": "rate limited"}, headers={"x-ratelimit-reset-tokens": "10ms"}
        )

    with pytest.raises(LLMUnavailableError, match="429"):
        await collect(client(handler, max_retries=2))


async def test_client_errors_are_not_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"error": "bad model"})

    with pytest.raises(LLMUnavailableError, match="400"):
        await collect(client(handler))
    assert calls["n"] == 1


async def test_api_key_sent_when_configured() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, content=sse(delta("x"), "[DONE]"))

    c = OpenAICompatibleClient("http://llm/v1", "m", api_key="k123")
    c._client = httpx.AsyncClient(
        base_url="http://llm/v1", transport=httpx.MockTransport(handler), headers=c._client.headers
    )
    await collect(c)
    assert seen["auth"] == "Bearer k123"
