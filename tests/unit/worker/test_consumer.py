"""Retry 3x with backoff, then dead-letter; permanent errors dead-letter immediately."""

import uuid
from dataclasses import dataclass, field
from typing import Any

from beai_rag_core.enums import JobKind
from beai_rag_core.queue import ATTEMPT_HEADER, DLX_EXCHANGE, IngestJob, retry_exchange
from worker.consumer import Consumer
from worker.parsers.base import ParseError


@dataclass
class FakeExchange:
    name: str
    published: list[tuple[Any, str]]

    async def publish(self, message: Any, routing_key: str) -> None:
        self.published.append((message, routing_key))


@dataclass
class FakeChannel:
    published: dict[str, list[tuple[Any, str]]] = field(default_factory=dict)

    async def get_exchange(self, name: str) -> FakeExchange:
        return FakeExchange(name, self.published.setdefault(name, []))


@dataclass
class FakeMessage:
    body: bytes
    headers: dict[str, Any]
    acked: bool = False
    rejected: bool = False

    async def ack(self) -> None:
        self.acked = True

    async def reject(self, requeue: bool = False) -> None:
        self.rejected = True


@dataclass
class FakeHandler:
    error: Exception | None
    retrying: list[str] = field(default_factory=list)
    failed: list[tuple[str, bool]] = field(default_factory=list)

    async def run(self, job: IngestJob) -> None:
        if self.error:
            raise self.error

    async def mark_retrying(self, job: IngestJob, error: str) -> None:
        self.retrying.append(error)

    async def mark_failed(self, job: IngestJob, error: str, *, dead_lettered: bool) -> None:
        self.failed.append((error, dead_lettered))


def job() -> IngestJob:
    return IngestJob(
        job_id=uuid.uuid4(),
        source_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        agent_id=uuid.uuid4(),
        kind=JobKind.INDEX,
    )


async def deliver(handler: FakeHandler, attempt: int) -> tuple[FakeChannel, FakeMessage]:
    ch = FakeChannel()
    msg = FakeMessage(job().model_dump_json().encode(), {ATTEMPT_HEADER: attempt})
    await Consumer(ch, handler, 2000).on_message(msg)  # type: ignore[arg-type]
    return ch, msg


async def test_success_acks() -> None:
    ch, msg = await deliver(FakeHandler(None), 0)
    assert msg.acked and not ch.published


async def test_transient_error_goes_to_next_retry_queue() -> None:
    for attempt in range(3):
        handler = FakeHandler(ConnectionError("embedder down"))
        ch, msg = await deliver(handler, attempt)
        assert msg.acked
        ((message, key),) = ch.published[retry_exchange(attempt + 1, 2000)]
        assert message.headers[ATTEMPT_HEADER] == attempt + 1
        assert key == "ingest.index"
        assert handler.retrying and not handler.failed


async def test_after_three_retries_dead_letter_with_message() -> None:
    handler = FakeHandler(ConnectionError("embedder down"))
    ch, msg = await deliver(handler, 3)
    assert msg.acked
    assert list(ch.published) == [DLX_EXCHANGE]
    ((error, dead),) = handler.failed
    assert dead and "Temporary problem" in error


async def test_permanent_error_skips_retries() -> None:
    handler = FakeHandler(ParseError("Could not read this document (PdfError)"))
    ch, _ = await deliver(handler, 0)
    assert list(ch.published) == [DLX_EXCHANGE]
    assert handler.failed == [("Could not read this document (PdfError)", True)]


async def test_malformed_message_rejected_to_dlq() -> None:
    ch = FakeChannel()
    msg = FakeMessage(b"{not json", {})
    await Consumer(ch, FakeHandler(None), 2000).on_message(msg)  # type: ignore[arg-type]
    assert msg.rejected and not msg.acked
