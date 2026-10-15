"""Queue consumer: runs jobs, retries transient failures 3x with backoff, then dead-letters.

Permanent failures (unreadable documents, blocked URLs) skip the retries: they are marked
``error`` with a human-readable message and sent to the dead-letter queue straight away.
"""

from __future__ import annotations

import logging
from typing import Protocol

from aio_pika.abc import AbstractChannel, AbstractIncomingMessage
from pydantic import ValidationError

from beai_rag_core.enums import JobKind
from beai_rag_core.queue import (
    ATTEMPT_HEADER,
    DLX_EXCHANGE,
    MAX_RETRIES,
    IngestJob,
    job_message,
    parse_job,
    queue_for,
    retry_exchange,
)
from worker.parsers.base import ParseError

logger = logging.getLogger(__name__)

PERMANENT_ERRORS: tuple[type[Exception], ...] = (ParseError,)


def human_message(exc: Exception) -> str:
    if isinstance(exc, PERMANENT_ERRORS):
        return str(exc) or "This source could not be read"
    return f"Temporary problem while indexing ({type(exc).__name__}). Please retry later."


class JobHandler(Protocol):
    """What the consumer needs from the pipeline (lets tests use a fake)."""

    async def run(self, job: IngestJob) -> None: ...

    async def mark_retrying(self, job: IngestJob, error: str) -> None: ...

    async def mark_failed(self, job: IngestJob, error: str, *, dead_lettered: bool) -> None: ...


class Consumer:
    def __init__(self, channel: AbstractChannel, handler: JobHandler, retry_base_ms: int) -> None:
        self._channel = channel
        self._handler = handler
        self._retry_base_ms = retry_base_ms

    async def on_message(self, message: AbstractIncomingMessage) -> None:
        try:
            job = parse_job(message.body)
        except (ValidationError, ValueError):
            logger.error("malformed job message; dead-lettering")
            await message.reject(requeue=False)  # queue's DLX -> ingest.dead
            return
        raw_attempt = (message.headers or {}).get(ATTEMPT_HEADER, 0)
        attempt = raw_attempt if isinstance(raw_attempt, int) else 0
        try:
            await self._handler.run(job)
        except Exception as exc:
            await self._on_failure(job, attempt, exc)
        await message.ack()

    async def _on_failure(self, job: IngestJob, attempt: int, exc: Exception) -> None:
        text = human_message(exc)
        permanent = isinstance(exc, PERMANENT_ERRORS)
        if not permanent and attempt < MAX_RETRIES:
            logger.warning(
                "job %s failed (attempt %d), retrying", job.job_id, attempt + 1, exc_info=exc
            )
            await self._handler.mark_retrying(job, text)
            exchange = await self._channel.get_exchange(
                retry_exchange(attempt + 1, self._retry_base_ms)
            )
            await exchange.publish(
                job_message(job, attempt=attempt + 1, error=repr(exc)),
                routing_key=queue_for(job.kind),
            )
            return
        logger.error("job %s failed permanently: %s", job.job_id, text, exc_info=exc)
        await self._handler.mark_failed(job, text, dead_lettered=True)
        dlx = await self._channel.get_exchange(DLX_EXCHANGE)
        await dlx.publish(job_message(job, attempt=attempt, error=repr(exc)), routing_key="")


async def consume(channel: AbstractChannel, handler: JobHandler, retry_base_ms: int) -> list[str]:
    consumer = Consumer(channel, handler, retry_base_ms)
    tags = []
    for kind in JobKind:
        queue = await channel.get_queue(queue_for(kind))
        tags.append(await queue.consume(consumer.on_message))
    return tags
