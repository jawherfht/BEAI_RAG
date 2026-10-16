"""RabbitMQ topology, job messages and the publisher (spec sections 2, 5 and 7).

Topology (all durable):
- exchange ``beai.ingest`` (direct) -> one queue per job type (``ingest.index``,
  ``ingest.reindex``, ``ingest.delete``, ``ingest.recrawl``), routing key = queue name.
- retry (declared by the worker only): exchange ``beai.ingest.retry.<n>.<delay>ms`` (fanout)
  -> queue ``ingest.retry.<n>.<delay>ms`` with that message TTL; expired messages dead-letter
  back to ``beai.ingest`` with their original routing key. Delays grow exponentially
  (base * 4^(n-1)). The delay is part of the name, so changing RETRY_BASE_MS never clashes
  with queues declared by an older config.
- dead letters: exchange ``beai.ingest.dlx`` (fanout) -> queue ``ingest.dead``.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractExchange, AbstractRobustConnection
from pydantic import BaseModel

from beai_rag_core.enums import JobKind

INGEST_EXCHANGE = "beai.ingest"
USAGE_QUEUE = "usage.events"  # credit management consumes this (spec section 7)
DLX_EXCHANGE = "beai.ingest.dlx"
DEAD_QUEUE = "ingest.dead"
MAX_RETRIES = 3
ATTEMPT_HEADER = "x-beai-attempt"
ERROR_HEADER = "x-beai-error"


def queue_for(kind: JobKind) -> str:
    return f"ingest.{kind.value}"


def retry_delay_ms(n: int, base_ms: int) -> int:
    return int(base_ms * 4 ** (n - 1))


def retry_exchange(n: int, base_ms: int) -> str:
    return f"beai.ingest.retry.{n}.{retry_delay_ms(n, base_ms)}ms"


def retry_queue(n: int, base_ms: int) -> str:
    return f"ingest.retry.{n}.{retry_delay_ms(n, base_ms)}ms"


class IngestJob(BaseModel):
    """Queue message. The worker re-reads tenant/agent from the source row and checks them."""

    job_id: uuid.UUID
    source_id: uuid.UUID
    tenant_id: uuid.UUID
    agent_id: uuid.UUID
    kind: JobKind


async def declare_topology(
    channel: AbstractChannel, retry_base_ms: int | None = None
) -> AbstractExchange:
    """Declare exchanges and queues. Retry queues only when ``retry_base_ms`` is given."""
    ingest = await channel.declare_exchange(
        INGEST_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True
    )
    dlx = await channel.declare_exchange(DLX_EXCHANGE, aio_pika.ExchangeType.FANOUT, durable=True)
    dead = await channel.declare_queue(DEAD_QUEUE, durable=True)
    await dead.bind(dlx)
    for kind in JobKind:
        name = queue_for(kind)
        q = await channel.declare_queue(
            name, durable=True, arguments={"x-dead-letter-exchange": DLX_EXCHANGE}
        )
        await q.bind(ingest, routing_key=name)
    for n in range(1, MAX_RETRIES + 1 if retry_base_ms is not None else 1):
        assert retry_base_ms is not None
        ex = await channel.declare_exchange(
            retry_exchange(n, retry_base_ms), aio_pika.ExchangeType.FANOUT, durable=True
        )
        q = await channel.declare_queue(
            retry_queue(n, retry_base_ms),
            durable=True,
            arguments={
                "x-message-ttl": retry_delay_ms(n, retry_base_ms),
                "x-dead-letter-exchange": INGEST_EXCHANGE,
            },
        )
        await q.bind(ex)
    return ingest


def job_message(job: IngestJob, attempt: int = 0, error: str | None = None) -> aio_pika.Message:
    headers: dict[str, Any] = {ATTEMPT_HEADER: attempt}
    if error:
        headers[ERROR_HEADER] = error[:1000]
    return aio_pika.Message(
        body=job.model_dump_json().encode(),
        content_type="application/json",
        delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        message_id=str(job.job_id),
        headers=headers,
    )


def parse_job(body: bytes) -> IngestJob:
    return IngestJob.model_validate(json.loads(body))


@dataclass
class QueuePublisher:
    """Publishes ingestion jobs. One robust connection per process, opened lazily."""

    url: str
    _connection: AbstractRobustConnection | None = None
    _channel: AbstractChannel | None = None
    _exchange: AbstractExchange | None = None
    _usage_declared: bool = False

    async def _ensure(self) -> AbstractExchange:
        if self._exchange is None or self._channel is None or self._channel.is_closed:
            self._usage_declared = False
            if self._connection is None or self._connection.is_closed:
                self._connection = await aio_pika.connect_robust(self.url, timeout=5)
            self._channel = await self._connection.channel(publisher_confirms=True)
            self._exchange = await declare_topology(self._channel)
        return self._exchange

    async def publish(self, job: IngestJob) -> None:
        exchange = await self._ensure()
        await exchange.publish(job_message(job), routing_key=queue_for(job.kind))

    async def publish_usage(self, event: dict[str, Any]) -> None:
        """One usage event per answer: tokens_in, tokens_out, rerank_used, ... (spec 7)."""
        await self._ensure()
        assert self._channel is not None
        if not self._usage_declared:
            await self._channel.declare_queue(USAGE_QUEUE, durable=True)
            self._usage_declared = True
        await self._channel.default_exchange.publish(
            aio_pika.Message(
                body=json.dumps(event, default=str).encode(),
                content_type="application/json",
                delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            ),
            routing_key=USAGE_QUEUE,
        )

    async def ping(self) -> None:
        await self._ensure()

    async def close(self) -> None:
        if self._connection is not None and not self._connection.is_closed:
            await self._connection.close()
        self._connection = self._channel = self._exchange = None
