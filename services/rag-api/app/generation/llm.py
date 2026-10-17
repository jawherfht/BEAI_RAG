"""OpenAI-compatible streaming chat client (spec section 6, step 8).

One client for every provider: vLLM on the GPU pool in production, any OpenAI-compatible
endpoint in dev (e.g. Groq). Differences are configuration only:
- ``thinking_switch``: how to disable reasoning ("chat_template_kwargs" for vLLM/SGLang,
  "reasoning_effort" for Groq, "none").
- ``api_key``: optional; omitted when a gateway/proxy injects the Authorization header.

Rate limits and transient errors (429, 5xx, connect/read errors) are retried with exponential
backoff BEFORE the first token, honouring ``Retry-After`` and ``x-ratelimit-reset-*``. Once
tokens have been streamed nothing is retried (the user would hear a repeat).
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx

logger = logging.getLogger(__name__)

ThinkingSwitch = Literal["chat_template_kwargs", "reasoning_effort", "none"]
RETRYABLE_STATUS = frozenset({408, 409, 425, 429, 500, 502, 503, 504})
_DURATION = re.compile(
    r"(?:(\d+(?:\.\d+)?)h)?(?:(\d+(?:\.\d+)?)m(?!s))?(?:(\d+(?:\.\d+)?)s)?(?:(\d+(?:\.\d+)?)ms)?$"
)


class LLMUnavailableError(RuntimeError):
    """The LLM could not be reached (after retries) or returned an error."""


@dataclass(frozen=True, slots=True)
class Usage:
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True, slots=True)
class LLMEvent:
    token: str | None = None
    usage: Usage | None = None
    # On the first token: seconds spent waiting on rate limits / retries before the request
    # that succeeded (so TTFT can be reported without queueing time).
    wait_s: float = 0.0


class LLMClient(Protocol):
    def stream(
        self, messages: Sequence[dict[str, str]], *, max_tokens: int, temperature: float
    ) -> AsyncIterator[LLMEvent]: ...

    async def ping(self) -> None: ...

    async def close(self) -> None: ...


def parse_duration_s(value: str | None) -> float | None:
    """Parse Retry-After / x-ratelimit-reset values: "2", "517ms", "2m52.8s", "1h2m"."""
    if not value:
        return None
    value = value.strip()
    try:
        return float(value)
    except ValueError:
        pass
    m = _DURATION.match(value)
    if not m or not any(m.groups()):
        return None
    h, mins, s, ms = (float(g) if g else 0.0 for g in m.groups())
    return h * 3600 + mins * 60 + s + ms / 1000


def retry_wait_s(headers: httpx.Headers, attempt: int, base_s: float, max_s: float) -> float:
    hinted = parse_duration_s(headers.get("retry-after"))
    if hinted is None:
        resets = [
            parse_duration_s(headers.get(h))
            for h in ("x-ratelimit-reset-tokens", "x-ratelimit-reset-requests")
        ]
        known = [r for r in resets if r is not None]
        hinted = min(known) if known else None
    if hinted is None:
        hinted = base_s * 2**attempt * (1 + random.random() * 0.25)  # noqa: S311 - jitter
    return min(max(hinted, 0.1), max_s)


class OpenAICompatibleClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        api_key: str | None = None,
        disable_thinking: bool = True,
        thinking_switch: ThinkingSwitch = "chat_template_kwargs",
        reasoning_effort: str = "none",
        timeout_s: float = 30.0,
        max_retries: int = 4,
        retry_base_s: float = 1.0,
        retry_max_wait_s: float = 20.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(timeout_s, connect=5.0),
        )
        self._model = model
        self._disable_thinking = disable_thinking
        self._switch = thinking_switch
        self._reasoning_effort = reasoning_effort
        self._max_retries = max_retries
        self._retry_base = retry_base_s
        self._retry_max = retry_max_wait_s

    @property
    def model(self) -> str:
        return self._model

    def request_body(
        self, messages: Sequence[dict[str, str]], *, max_tokens: int, temperature: float
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": list(messages),
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if self._disable_thinking:
            if self._switch == "chat_template_kwargs":
                body["chat_template_kwargs"] = {"enable_thinking": False}
            elif self._switch == "reasoning_effort":
                body["reasoning_effort"] = self._reasoning_effort
        return body

    async def stream(
        self, messages: Sequence[dict[str, str]], *, max_tokens: int, temperature: float
    ) -> AsyncIterator[LLMEvent]:
        body = self.request_body(messages, max_tokens=max_tokens, temperature=temperature)
        attempt = 0
        waited = 0.0
        while True:
            started = False
            try:
                async with self._client.stream("POST", "/chat/completions", json=body) as resp:
                    if resp.status_code != 200:
                        await resp.aread()
                        if resp.status_code in RETRYABLE_STATUS and attempt < self._max_retries:
                            wait = retry_wait_s(
                                resp.headers, attempt, self._retry_base, self._retry_max
                            )
                            logger.warning(
                                "LLM %s, retry %d in %.1fs", resp.status_code, attempt + 1, wait
                            )
                            attempt += 1
                            waited += wait
                            await asyncio.sleep(wait)
                            continue
                        raise LLMUnavailableError(
                            f"LLM returned {resp.status_code}: {resp.text[:300]}"
                        )
                    think = _ThinkFilter()
                    async for line in resp.aiter_lines():
                        event = _parse_sse_line(line)
                        if event is None:
                            continue
                        if event == "[DONE]":
                            break
                        if event.token:
                            text = think.feed(event.token)
                            if text:
                                first = not started
                                started = True
                                yield LLMEvent(token=text, wait_s=waited if first else 0.0)
                        if event.usage:
                            yield event
                    return
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                if started or attempt >= self._max_retries:
                    raise LLMUnavailableError(f"LLM unreachable: {exc!r}") from exc
                wait = min(self._retry_base * 2**attempt, self._retry_max)
                logger.warning("LLM transport error %r, retry %d in %.1fs", exc, attempt + 1, wait)
                attempt += 1
                waited += wait
                await asyncio.sleep(wait)

    async def ping(self) -> None:
        resp = await self._client.get("/models")
        resp.raise_for_status()

    async def close(self) -> None:
        await self._client.aclose()


def _parse_sse_line(line: str) -> LLMEvent | Literal["[DONE]"] | None:
    if not line.startswith("data:"):
        return None
    data = line[5:].strip()
    if data == "[DONE]":
        return "[DONE]"
    try:
        chunk = json.loads(data)
    except json.JSONDecodeError:
        return None
    if "error" in chunk:
        raise LLMUnavailableError(f"LLM stream error: {str(chunk['error'])[:300]}")
    token = None
    choices = chunk.get("choices") or []
    if choices:
        token = (choices[0].get("delta") or {}).get("content")
    raw_usage = chunk.get("usage") or (chunk.get("x_groq") or {}).get("usage")
    usage = (
        Usage(int(raw_usage.get("prompt_tokens", 0)), int(raw_usage.get("completion_tokens", 0)))
        if raw_usage
        else None
    )
    if token is None and usage is None:
        return None
    return LLMEvent(token=token, usage=usage)


class _ThinkFilter:
    """Drops a ``<think>...</think>`` block if a model emits one despite the switch."""

    def __init__(self) -> None:
        self._buf = ""
        self._state: Literal["start", "think", "answer"] = "start"

    def feed(self, token: str) -> str:
        if self._state == "answer":
            return token
        self._buf += token
        if self._state == "start":
            stripped = self._buf.lstrip()
            if not stripped:
                return ""
            if "<think>".startswith(stripped[:7]) and len(stripped) < 7:
                return ""
            if stripped.startswith("<think>"):
                self._state = "think"
            else:
                self._state = "answer"
                out, self._buf = self._buf, ""
                return out
        if self._state == "think" and "</think>" in self._buf:
            out = self._buf.split("</think>", 1)[1].lstrip()
            self._state, self._buf = "answer", ""
            return out
        return ""


def now_ms() -> float:
    return time.perf_counter() * 1000
