"""S3-compatible object storage (SeaweedFS in dev). Keys are always prefixed by tenant."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from aiobotocore.config import AioConfig
from aiobotocore.session import get_session
from botocore.exceptions import ClientError

from beai_rag_core.settings import CoreSettings
from beai_rag_core.tenancy import TenantScope

_UNSAFE = re.compile(r"[^\w.\- ()\[\]]+", re.UNICODE)


def safe_file_name(file_name: str) -> str:
    name = file_name.replace("\\", "/").rsplit("/", 1)[-1]
    name = _UNSAFE.sub("_", name).strip(" .")
    return name[:200] or "file"


def source_prefix(scope: TenantScope, source_id: UUID) -> str:
    return f"tenants/{scope.tenant_id}/agents/{scope.agent_id}/sources/{source_id}/"


def source_object_key(scope: TenantScope, source_id: UUID, file_name: str) -> str:
    return source_prefix(scope, source_id) + safe_file_name(file_name)


def parsed_cache_key(scope: TenantScope, source_id: UUID) -> str:
    """Parsed document cache, so re-chunking (slider change) does not re-parse."""
    return source_prefix(scope, source_id) + "_parsed.json"


class ObjectStorage:
    def __init__(self, settings: CoreSettings, timeout_s: float | None = None) -> None:
        self._settings = settings
        self._timeout = timeout_s or settings.s3_timeout_s
        self._session = get_session()

    @property
    def bucket(self) -> str:
        return self._settings.s3_bucket

    @asynccontextmanager
    async def client(self) -> AsyncIterator[Any]:
        s = self._settings
        async with self._session.create_client(
            "s3",
            endpoint_url=s.s3_endpoint,
            region_name=s.s3_region,
            aws_access_key_id=s.s3_access_key.get_secret_value(),
            aws_secret_access_key=s.s3_secret_key.get_secret_value(),
            config=AioConfig(
                connect_timeout=self._timeout,
                read_timeout=self._timeout,
                retries={"max_attempts": 2},
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

    async def put(self, key: str, body: bytes, content_type: str) -> None:
        async with self.client() as c:
            await c.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType=content_type)

    async def get(self, key: str) -> bytes:
        async with self.client() as c:
            resp = await c.get_object(Bucket=self.bucket, Key=key)
            async with resp["Body"] as stream:
                data: bytes = await stream.read()
                return data

    async def get_optional(self, key: str) -> bytes | None:
        try:
            return await self.get(key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                return None
            raise

    async def delete_prefix(self, prefix: str) -> int:
        """Delete every object under a (tenant-prefixed) key prefix."""
        if not prefix.startswith("tenants/") or not prefix.endswith("/"):
            raise ValueError("refusing to delete outside a tenant source prefix")
        deleted = 0
        async with self.client() as c:
            paginator = c.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
                if keys:
                    await c.delete_objects(Bucket=self.bucket, Delete={"Objects": keys})
                    deleted += len(keys)
        return deleted
