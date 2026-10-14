"""S3-compatible object storage (MinIO in dev). Keys are always prefixed by tenant."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from aiobotocore.config import AioConfig
from aiobotocore.session import get_session
from botocore.exceptions import ClientError

from app.config import Settings
from beai_rag_core.tenancy import TenantScope


def source_object_key(scope: TenantScope, source_id: UUID, file_name: str) -> str:
    safe_name = file_name.replace("/", "_").replace("\\", "_").lstrip(".") or "file"
    return f"tenants/{scope.tenant_id}/agents/{scope.agent_id}/sources/{source_id}/{safe_name}"


class ObjectStorage:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session = get_session()

    @property
    def bucket(self) -> str:
        return self._settings.s3_bucket

    @asynccontextmanager
    async def client(self) -> AsyncIterator[Any]:
        s = self._settings
        timeout = s.readiness_timeout_s
        async with self._session.create_client(
            "s3",
            endpoint_url=s.s3_endpoint,
            region_name=s.s3_region,
            aws_access_key_id=s.s3_access_key.get_secret_value(),
            aws_secret_access_key=s.s3_secret_key.get_secret_value(),
            config=AioConfig(
                connect_timeout=timeout,
                read_timeout=timeout,
                retries={"max_attempts": 1},
                s3={"addressing_style": "path"},
            ),
        ) as client:
            yield client

    async def ping(self) -> bool:
        async with self.client() as c:
            await c.head_bucket(Bucket=self.bucket)
        return True

    async def ensure_bucket(self) -> None:
        async with self.client() as c:
            try:
                await c.head_bucket(Bucket=self.bucket)
            except ClientError:
                await c.create_bucket(Bucket=self.bucket)
