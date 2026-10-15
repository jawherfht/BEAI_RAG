"""Request/response models for the knowledge-base and source endpoints (spec section 7)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator

from beai_rag_core import kb_rules
from beai_rag_core.enums import KnowledgeBaseStatus, SourceStatus, SourceType


class KnowledgeBaseSettingsIn(BaseModel):
    """PUT body. Omitted fields keep their current value (or the default on create)."""

    model_config = ConfigDict(extra="forbid")

    chunk_size: int | None = None
    top_k: int | None = None
    fallback_message: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    hybrid_enabled: bool | None = None
    rerank_enabled: bool | None = None
    rag_enabled: bool | None = None

    @field_validator("chunk_size")
    @classmethod
    def _chunk_size(cls, v: int | None) -> int | None:
        return None if v is None else kb_rules.validate_chunk_size(v)

    @field_validator("top_k")
    @classmethod
    def _top_k(cls, v: int | None) -> int | None:
        return None if v is None else kb_rules.validate_top_k(v)


class SourceCountsOut(BaseModel):
    files: int
    urls: int
    business_info: int


class KnowledgeBaseOut(BaseModel):
    agent_id: uuid.UUID
    status: KnowledgeBaseStatus
    rag_enabled: bool
    chunk_size: int
    chunk_overlap: int
    top_k: int
    fallback_message: str
    hybrid_enabled: bool
    rerank_enabled: bool
    embed_model: str | None
    kb_version: int
    counts: SourceCountsOut
    reindexing: bool = False


class KnowledgeBaseStatusOut(BaseModel):
    files: int
    urls: int
    rag_enabled: bool
    status: KnowledgeBaseStatus
    label: str


class SourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: SourceType
    status: SourceStatus
    file_name: str | None
    mime_type: str | None
    size_bytes: int | None
    url: str | None
    crawl_depth: int
    max_pages: int
    recrawl_interval_hours: int | None
    title: str | None
    language: str | None
    pages: int | None
    chunks: int | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    last_indexed_at: datetime | None


class SourceAccepted(BaseModel):
    source_id: uuid.UUID
    status: SourceStatus
    file_name: str | None = None
    url: str | None = None
    duplicate: bool = False


class UrlSourceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: AnyHttpUrl
    crawl_depth: int = Field(default=1, ge=0, le=kb_rules.CRAWL_DEPTH_MAX)
    max_pages: int = Field(default=50, ge=1, le=kb_rules.MAX_PAGES_MAX)
    recrawl_interval_hours: int | None = Field(default=None, ge=1, le=24 * 365)


class FaqItem(BaseModel):
    question: Annotated[str, Field(min_length=1, max_length=500)]
    answer: Annotated[str, Field(min_length=1, max_length=2000)]


class BusinessInfoIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: Annotated[str, Field(max_length=200)] = ""
    hours: Annotated[str, Field(max_length=1000)] = ""
    address: Annotated[str, Field(max_length=500)] = ""
    contact: Annotated[str, Field(max_length=500)] = ""
    faq: Annotated[list[FaqItem], Field(max_length=50)] = []

    def is_empty(self) -> bool:
        return not any([self.company_name, self.hours, self.address, self.contact, self.faq])
