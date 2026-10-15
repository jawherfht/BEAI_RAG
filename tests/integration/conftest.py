"""Integration fixtures: real Qdrant, Postgres, Redis, RabbitMQ and MinIO via testcontainers."""

from __future__ import annotations

import socket
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from testcontainers.core.container import DockerContainer

from tests.integration.images import IMAGES

QDRANT_API_KEY = "it-qdrant-key"
ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = ROOT / "services/rag-api/alembic.ini"
SEAWEEDFS_S3_CONFIG = ROOT / "deploy/dev/seaweedfs-s3.json"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/integration" in str(item.path):
            item.add_marker(pytest.mark.integration)


@dataclass(frozen=True)
class Infra:
    qdrant_url: str
    database_url: str
    redis_url: str
    rabbitmq_url: str
    s3_endpoint: str

    def settings_overrides(self) -> dict[str, object]:
        return {
            "qdrant_url": self.qdrant_url,
            "qdrant_api_key": QDRANT_API_KEY,
            "database_url": self.database_url,
            "redis_url": self.redis_url,
            "rabbitmq_url": self.rabbitmq_url,
            "s3_endpoint": self.s3_endpoint,
            "s3_access_key": "minio",
            "s3_secret_key": "minio123",
        }


def _wait(probe: Callable[[], bool], what: str, timeout_s: float = 120.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if probe():
                return
        except Exception:  # noqa: S110 - not ready yet
            pass
        time.sleep(0.5)
    raise TimeoutError(f"{what} did not become ready")


def _amqp_ready(host: str, port: int) -> bool:
    """AMQP 0-9-1 handshake: the broker answers the protocol header with a method frame."""
    with socket.create_connection((host, port), timeout=2) as sock:
        sock.sendall(b"AMQP\x00\x00\x09\x01")
        return sock.recv(1) == b"\x01"


def _start(name: str) -> DockerContainer:
    image = IMAGES[name]
    if name == "qdrant":
        c = DockerContainer(image).with_env("QDRANT__SERVICE__API_KEY", QDRANT_API_KEY)
        c = c.with_exposed_ports(6333)
    elif name == "postgres":
        c = (
            DockerContainer(image)
            .with_env("POSTGRES_USER", "beai")
            .with_env("POSTGRES_PASSWORD", "beai")
            .with_env("POSTGRES_DB", "beai_rag")
            .with_exposed_ports(5432)
        )
    elif name == "redis":
        c = DockerContainer(image).with_exposed_ports(6379)
    elif name == "rabbitmq":
        c = DockerContainer(image).with_exposed_ports(5672)
    else:
        c = (
            DockerContainer(image)
            .with_volume_mapping(str(SEAWEEDFS_S3_CONFIG), "/etc/seaweedfs/s3.json", "ro")
            .with_command(
                "server -dir=/data -s3 -s3.port=8333 -s3.config=/etc/seaweedfs/s3.json "
                "-master.volumeSizeLimitMB=64 -volume.max=0"
            )
            .with_exposed_ports(8333)
        )
    c.start()
    return c


def _wait_ready(name: str, c: DockerContainer) -> None:
    host = c.get_container_host_ip()
    if name == "qdrant":
        port = c.get_exposed_port(6333)
        _wait(lambda: httpx.get(f"http://{host}:{port}/readyz").status_code == 200, name)
    elif name == "postgres":
        _wait(lambda: c.exec("pg_isready -U beai -d beai_rag -h 127.0.0.1").exit_code == 0, name)
    elif name == "redis":
        _wait(lambda: c.exec("redis-cli ping").output.strip() == b"PONG", name)
    elif name == "rabbitmq":
        # No `docker exec` probe here: running rabbitmq-diagnostics as root before the broker
        # starts creates a root-owned .erlang.cookie and the broker then crashes.
        amqp_port = int(c.get_exposed_port(5672))
        _wait(lambda: _amqp_ready(host, amqp_port), name)
    else:
        port = c.get_exposed_port(8333)
        _wait(lambda: httpx.get(f"http://{host}:{port}/healthz").status_code == 200, name)


@pytest.fixture(scope="session")
def infra() -> Iterator[Infra]:
    names = list(IMAGES)
    # Start one container first so testcontainers' reaper (Ryuk) is created only once.
    containers = {names[0]: _start(names[0])}
    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        containers.update(zip(names[1:], pool.map(_start, names[1:]), strict=True))
        list(pool.map(lambda n: _wait_ready(n, containers[n]), names))
    try:

        def addr(name: str, port: int) -> str:
            c = containers[name]
            return f"{c.get_container_host_ip()}:{c.get_exposed_port(port)}"

        yield Infra(
            qdrant_url=f"http://{addr('qdrant', 6333)}",
            database_url=f"postgresql+asyncpg://beai:beai@{addr('postgres', 5432)}/beai_rag",
            redis_url=f"redis://{addr('redis', 6379)}/0",
            rabbitmq_url=f"amqp://guest:guest@{addr('rabbitmq', 5672)}/",
            s3_endpoint=f"http://{addr('seaweedfs', 8333)}",
        )
    finally:
        for c in containers.values():
            c.stop()


def alembic_config(database_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


@pytest.fixture(scope="session")
def migrated(infra: Infra) -> Infra:
    command.upgrade(alembic_config(infra.database_url), "head")
    return infra


# ---- Phase 2 fixtures: API client + in-process worker ---------------------------------

import contextlib  # noqa: E402
import uuid  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402

import aio_pika  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402
from app.resources import Resources  # noqa: E402
from beai_rag_core.embedding.tokenizer import WhitespaceTokenCounter  # noqa: E402
from beai_rag_core.enums import JobKind  # noqa: E402
from beai_rag_core.queue import declare_topology, queue_for  # noqa: E402
from tests.fakes import HashingEmbedder, HashingSparse  # noqa: E402
from tests.helpers import make_settings, make_token  # noqa: E402
from worker.consumer import consume  # noqa: E402
from worker.parsers.docling_parser import DoclingParser  # noqa: E402
from worker.parsers.web_crawler import WebCrawler  # noqa: E402
from worker.pipeline import IngestionPipeline  # noqa: E402


@dataclass
class Tenant:
    tenant_id: uuid.UUID
    agent_id: uuid.UUID

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {make_token(self.tenant_id, [self.agent_id])}"}

    @property
    def base(self) -> str:
        return f"/v1/agents/{self.agent_id}"


def new_tenant() -> Tenant:
    return Tenant(uuid.uuid4(), uuid.uuid4())


def api_settings(infra: Infra, **overrides: object) -> Settings:
    values: dict[str, object] = {
        **infra.settings_overrides(),
        "qdrant_auto_create": True,
        "s3_auto_create_bucket": True,
        "readiness_timeout_s": 3.0,
        **overrides,
    }
    return make_settings(**values)


@dataclass
class Api:
    client: AsyncClient
    resources: Resources


@contextlib.asynccontextmanager
async def running_api(infra: Infra, **overrides: object) -> AsyncIterator[Api]:
    app = create_app(api_settings(infra, **overrides))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://api") as client:
            yield Api(client, app.state.resources)


async def drain_queue(
    rabbitmq_url: str, kind: JobKind
) -> list[aio_pika.abc.AbstractIncomingMessage]:
    connection = await aio_pika.connect(rabbitmq_url)
    async with connection:
        channel = await connection.channel()
        await declare_topology(channel)
        queue = await channel.get_queue(queue_for(kind))
        out = []
        while (msg := await queue.get(no_ack=True, fail=False)) is not None:
            out.append(msg)
        return out


TEST_RETRY_BASE_MS = 200


@dataclass
class Worker:
    pipeline: IngestionPipeline
    dense: HashingEmbedder


@contextlib.asynccontextmanager
async def running_worker(
    api: Api, *, dense: HashingEmbedder | None = None
) -> AsyncIterator[Worker]:
    r = api.resources
    dense = dense or HashingEmbedder(r.settings.embed_dim)
    pipeline = IngestionPipeline(
        sessionmaker=r.sessionmaker,
        store=r.store,
        storage=r.storage,
        dense=dense,
        sparse=HashingSparse(),
        counter=WhitespaceTokenCounter(),
        parser=DoclingParser(ocr=False),
        crawler=WebCrawler(),
        embed_model_tag="test-hashing@1",
    )
    connection = await aio_pika.connect_robust(r.settings.rabbitmq_url.get_secret_value())
    channel = await connection.channel()
    await channel.set_qos(prefetch_count=2)
    await declare_topology(channel, TEST_RETRY_BASE_MS)
    await consume(channel, pipeline, TEST_RETRY_BASE_MS)
    try:
        yield Worker(pipeline, dense)
    finally:
        await connection.close()
