"""Answer pipeline (spec section 6): cache -> retrieve -> grounding -> prompt -> LLM stream ->
citations -> cache, usage event, sampled answers_log, metrics.

``answer_events`` yields TokenEvent* -> SourcesEvent -> DoneEvent for every caller (/test,
/answer SSE, WebSocket, gRPC). Ungrounded questions return the fallback message WITHOUT calling
the LLM. If the LLM is unavailable after retries, the fallback message is returned with
``error="llm_unavailable"`` (and nothing is cached).
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import logging
import random
import re
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.cache.answer_cache import normalize_question
from app.generation.citations import (
    SpokenStream,
    is_fallback_answer,
    parse_answer,
    to_spoken,
)
from app.generation.llm import LLMUnavailableError
from app.generation.pii import scrub
from app.generation.prompt import Persona, Turn, build_prompt
from app.resources import Resources
from app.services.retrieval import AgentKnowledge, load_agent_knowledge, retrieve
from app.telemetry.metrics import (
    ANSWER_CACHE_HITS,
    ANSWERS_TOTAL,
    FALLBACK_TOTAL,
    LLM_ERRORS,
    observe_latency,
)
from beai_rag_core.db.models import AnswerLog
from beai_rag_core.enums import Confidence
from beai_rag_core.tenancy import TenantScope

logger = logging.getLogger(__name__)
_WORDS = re.compile(r"\S+\s*")


@dataclass(frozen=True, slots=True)
class AnswerRequest:
    question: str
    language: str | None = None
    persona: Persona = field(default_factory=Persona)
    history: Sequence[Turn] = ()


@dataclass(frozen=True, slots=True)
class TokenEvent:
    text: str  # display delta (may contain [n] markers)
    spoken: str  # TTS delta (markers removed)


@dataclass(frozen=True, slots=True)
class SourcesEvent:
    sources: list[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class DoneEvent:
    display_text: str
    spoken_text: str
    sources: list[dict[str, Any]]
    confidence: Confidence
    fallback: bool
    latency_ms: dict[str, float]
    cache_hit: bool = False
    error: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "answer": self.display_text,
            "spoken_text": self.spoken_text,
            "sources": self.sources,
            "confidence": self.confidence.value,
            "fallback": self.fallback,
            "latency_ms": self.latency_ms,
            "cache_hit": self.cache_hit,
            "error": self.error,
        }


AnswerEvent = TokenEvent | SourcesEvent | DoneEvent


def _cache_question(req: AnswerRequest) -> str | None:
    """Cache only stateless questions; persona and language change the answer, so they are
    part of the key (hashed together with tenant, agent and kb_version by the cache)."""
    if req.history:
        return None
    persona = json.dumps(dataclasses.asdict(req.persona), sort_keys=True)
    digest = hashlib.sha256(f"{persona}|{req.language or ''}".encode()).hexdigest()[:16]
    return f"{normalize_question(req.question)}\u241f{digest}"


async def _replay(text: str) -> AsyncIterator[str]:
    for word in _WORDS.findall(text):
        yield word


class AnswerService:
    def __init__(self, resources: Resources) -> None:
        self._r = resources

    async def answer_events(
        self, scope: TenantScope, req: AnswerRequest
    ) -> AsyncIterator[AnswerEvent]:
        r = self._r
        s = r.settings
        t0 = time.perf_counter()
        async with r.sessionmaker() as session:
            knowledge = await load_agent_knowledge(session, scope)
        if not knowledge.rag_enabled:
            async for ev in self._fallback(knowledge, {"total": _ms(t0)}, reason="rag_disabled"):
                yield ev
            return

        cache_q = _cache_question(req)
        if cache_q is not None:
            cached = await r.answer_cache.get(scope, knowledge.kb_version, cache_q)
            if cached is not None:
                ANSWER_CACHE_HITS.inc()
                async for word in _replay(cached["answer"]):
                    yield TokenEvent(word, to_spoken(word))
                yield SourcesEvent(cached["sources"])
                yield DoneEvent(
                    display_text=cached["answer"],
                    spoken_text=cached["spoken_text"],
                    sources=cached["sources"],
                    confidence=Confidence(cached["confidence"]),
                    fallback=cached["fallback"],
                    latency_ms={"cache": 0.0, "total": _ms(t0)},
                    cache_hit=True,
                )
                return

        result, _ = await retrieve(r, scope, knowledge, req.question)
        latency = {k: result.latency_ms.get(k, 0.0) for k in ("embed", "search", "rerank")}
        if result.fallback:
            latency["total"] = _ms(t0)
            done: DoneEvent | None = None
            async for ev in self._fallback(knowledge, latency, reason="below_threshold"):
                if isinstance(ev, DoneEvent):
                    done = ev
                yield ev
            if done is not None and cache_q is not None:
                await self._cache(scope, knowledge, cache_q, done)
            self._after(scope, req, done, result.reranked or result.rerank_checked)
            return

        prompt = build_prompt(
            persona=req.persona,
            fallback_message=knowledge.fallback_message,
            chunks=result.chunks,
            question=req.question,
            history=req.history,
            max_input_tokens=s.llm_max_input_tokens,
        )
        raw: list[str] = []
        spoken = SpokenStream()
        tokens_in = tokens_out = 0
        t_llm = time.perf_counter()
        ttft: float | None = None
        waited_ms = 0.0
        try:
            async for event in r.llm.stream(
                prompt.messages, max_tokens=s.llm_max_tokens, temperature=s.llm_temperature
            ):
                if event.token:
                    if ttft is None:
                        waited_ms = event.wait_s * 1000
                        ttft = _ms(t_llm) - waited_ms
                    raw.append(event.token)
                    yield TokenEvent(event.token, spoken.feed(event.token))
                if event.usage:
                    tokens_in, tokens_out = event.usage.prompt_tokens, event.usage.completion_tokens
        except LLMUnavailableError as exc:
            LLM_ERRORS.inc()
            logger.error("LLM unavailable: %s", exc)
            if not raw:
                latency["total"] = _ms(t0)
                async for ev in self._fallback(
                    knowledge, latency, reason="llm_unavailable", error="llm_unavailable"
                ):
                    yield ev
                return
            # Tokens already went out: finish with what we have.
        tail = spoken.flush()
        if tail:
            yield TokenEvent("", tail)
        latency["llm_ttft"] = ttft or 0.0
        latency["llm_total"] = _ms(t_llm) - waited_ms
        if waited_ms:
            latency["llm_rate_limit_wait"] = waited_ms
        latency["total"] = _ms(t0)

        text = "".join(raw)
        parsed = parse_answer(text, prompt.used_chunks)
        if is_fallback_answer(text, knowledge.fallback_message):
            confidence, fallback, sources = Confidence.LOW, True, []
            FALLBACK_TOTAL.labels("llm").inc()
        else:
            fallback = False
            sources = [src.as_dict() for src in parsed.sources]
            confidence = result.confidence
            if not parsed.cited and confidence is Confidence.HIGH:
                confidence = Confidence.MEDIUM  # answer cites nothing (spec 6, step 6)
        yield SourcesEvent(sources)
        done = DoneEvent(
            display_text=parsed.display_text,
            spoken_text=parsed.spoken_text,
            sources=sources,
            confidence=confidence,
            fallback=fallback,
            latency_ms={k: round(v, 1) for k, v in latency.items()},
            tokens_in=tokens_in or prompt.estimated_tokens,
            tokens_out=tokens_out or max(1, len(text) // 4),
        )
        yield done
        if cache_q is not None:
            await self._cache(scope, knowledge, cache_q, done)
        self._after(scope, req, done, result.reranked or result.rerank_checked)

    async def _fallback(
        self,
        knowledge: AgentKnowledge,
        latency: dict[str, float],
        *,
        reason: str,
        error: str | None = None,
    ) -> AsyncIterator[AnswerEvent]:
        message = knowledge.fallback_message
        FALLBACK_TOTAL.labels(reason).inc()
        async for word in _replay(message):
            yield TokenEvent(word, word)
        yield SourcesEvent([])
        yield DoneEvent(
            display_text=message,
            spoken_text=to_spoken(message),
            sources=[],
            confidence=Confidence.LOW,
            fallback=True,
            latency_ms={k: round(v, 1) for k, v in latency.items()},
            error=error,
        )

    async def _cache(
        self, scope: TenantScope, knowledge: AgentKnowledge, cache_q: str, done: DoneEvent
    ) -> None:
        if done.error:
            return
        try:
            await self._r.answer_cache.set(
                scope,
                knowledge.kb_version,
                cache_q,
                {
                    "answer": done.display_text,
                    "spoken_text": done.spoken_text,
                    "sources": done.sources,
                    "confidence": done.confidence.value,
                    "fallback": done.fallback,
                },
            )
        except Exception:
            logger.exception("answer cache write failed")

    def _after(
        self, scope: TenantScope, req: AnswerRequest, done: DoneEvent | None, reranked: bool
    ) -> None:
        """Metrics now; usage event and sampled log in the background (never delay the answer)."""
        if done is None:
            return
        ANSWERS_TOTAL.labels(done.confidence.value).inc()
        observe_latency(done.latency_ms)
        task = asyncio.create_task(self._side_effects(scope, req, done, reranked))
        _BACKGROUND.add(task)
        task.add_done_callback(_BACKGROUND.discard)

    async def _side_effects(
        self, scope: TenantScope, req: AnswerRequest, done: DoneEvent, reranked: bool
    ) -> None:
        r = self._r
        try:
            await r.publisher.publish_usage(
                {
                    "type": "rag.answer",
                    "tenant_id": str(scope.tenant_id),
                    "agent_id": str(scope.agent_id),
                    "tokens_in": done.tokens_in,
                    "tokens_out": done.tokens_out,
                    "rerank_used": reranked,
                    "fallback": done.fallback,
                    "llm_model": r.settings.llm_model if done.tokens_out else None,
                    "ts": time.time(),
                }
            )
        except Exception:
            logger.exception("usage event publish failed")
        if random.random() >= r.settings.answer_log_sample_rate:  # noqa: S311 - sampling
            return
        try:
            async with r.sessionmaker() as session:
                session.add(
                    AnswerLog(
                        tenant_id=scope.tenant_id,
                        agent_id=scope.agent_id,
                        question=scrub(req.question),
                        answer=scrub(done.display_text),
                        sources=done.sources,
                        confidence=done.confidence,
                        fallback=done.fallback,
                        latency_ms=done.latency_ms,
                    )
                )
                await session.commit()
        except Exception:
            logger.exception("answers_log write failed")


_BACKGROUND: set[asyncio.Task[None]] = set()


def _ms(start: float) -> float:
    return (time.perf_counter() - start) * 1000
