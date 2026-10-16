"""POST /test (JSON), POST /answer (SSE) and WS /ws (spec section 7).

All three run the same pipeline (``AnswerService``). SSE events: ``token`` {text, spoken},
``sources`` {sources}, ``done`` {answer, spoken_text, sources, confidence, fallback,
latency_ms, cache_hit, error}. The WebSocket sends the same payloads as JSON messages with a
``type`` field and accepts several questions on one connection.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from app.api.deps import ResourcesDep
from app.api.schemas import AnswerIn, TestAnswerOut
from app.auth import AgentScopeDep, scope_from_websocket
from app.domain.errors import AppError
from app.generation.prompt import Persona, Turn
from app.services.answer import (
    AnswerEvent,
    AnswerRequest,
    AnswerService,
    DoneEvent,
    SourcesEvent,
    TokenEvent,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/agents/{agent_id}", tags=["answer"])


def to_request(body: AnswerIn) -> AnswerRequest:
    persona = Persona(**body.persona.model_dump()) if body.persona else Persona()
    return AnswerRequest(
        question=body.question,
        language=body.language,
        persona=persona,
        history=[Turn(t.role, t.text) for t in body.conversation_history],
    )


def event_payload(ev: AnswerEvent) -> tuple[str, dict[str, Any]]:
    if isinstance(ev, TokenEvent):
        return "token", {"text": ev.text, "spoken": ev.spoken}
    if isinstance(ev, SourcesEvent):
        return "sources", {"sources": ev.sources}
    return "done", ev.as_dict()


@router.post("/test", response_model=TestAnswerOut)
async def test_agent(
    body: AnswerIn, scope: AgentScopeDep, resources: ResourcesDep
) -> TestAnswerOut:
    """ "Test this agent" panel: the full pipeline, returned as one JSON object."""
    done: DoneEvent | None = None
    async for ev in AnswerService(resources).answer_events(scope, to_request(body)):
        if isinstance(ev, DoneEvent):
            done = ev
    assert done is not None
    return TestAnswerOut.model_validate(done.as_dict())


@router.post("/answer", responses={200: {"content": {"text/event-stream": {}}}})
async def answer_sse(
    body: AnswerIn, scope: AgentScopeDep, resources: ResourcesDep
) -> StreamingResponse:
    events = AnswerService(resources).answer_events(scope, to_request(body))
    first = await anext(events)  # errors (e.g. 404) surface before the stream starts

    async def stream() -> AsyncIterator[bytes]:
        ev: AnswerEvent = first
        while True:
            name, data = event_payload(ev)
            yield f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()
            try:
                ev = await anext(events)
            except StopAsyncIteration:
                return

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.websocket("/ws")
async def answer_ws(websocket: WebSocket, agent_id: str) -> None:
    resources = websocket.app.state.resources
    try:
        scope = scope_from_websocket(websocket, agent_id, resources.settings)
    except AppError as exc:
        await websocket.close(code=4401 if exc.status_code == 401 else 4404)
        return
    await websocket.accept()
    service = AnswerService(resources)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                body = AnswerIn.model_validate_json(raw)
            except ValidationError as exc:
                await websocket.send_json(
                    {
                        "type": "error",
                        "code": "validation_error",
                        "details": exc.errors(include_url=False),
                    }
                )
                continue
            try:
                async for ev in service.answer_events(scope, to_request(body)):
                    name, data = event_payload(ev)
                    await websocket.send_json({"type": name, **data})
            except AppError as exc:
                await websocket.send_json(
                    {"type": "error", "code": exc.code, "message": exc.message}
                )
    except WebSocketDisconnect:
        return
