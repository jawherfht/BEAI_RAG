"""Request/response models for the knowledge-base and source endpoints (spec section 7)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

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


# ---- answering (Phase 4) ------------------------------------------------------------------


class PersonaIn(BaseModel):
    """Personality settings, read only to build the system prompt (spec section 1.3)."""

    model_config = ConfigDict(extra="forbid")

    agent_name: Annotated[str, Field(max_length=100)] = "this assistant"
    role: Annotated[str, Field(max_length=500)] = "helpful assistant"
    instructions: Annotated[str, Field(max_length=1000)] = ""
    tone: Annotated[str, Field(max_length=100)] = "friendly"
    response_style: Annotated[str, Field(max_length=100)] = "concise"
    boundaries: Annotated[str, Field(max_length=500)] = "only topics covered by the knowledge base"


class TurnIn(BaseModel):
    role: Literal["user", "assistant"]
    text: Annotated[str, Field(max_length=2000)]


class AnswerIn(BaseModel):
    """The tenant and agent come from the auth context, never from this body."""

    model_config = ConfigDict(extra="forbid")

    question: Annotated[str, Field(min_length=1, max_length=1000)]
    language: Annotated[str, Field(max_length=16)] | None = None
    persona: PersonaIn | None = None
    conversation_history: Annotated[list[TurnIn], Field(max_length=20)] = []


class SourceRef(BaseModel):
    file_name: str | None
    page: int | None
    section: str | None
    url: str | None
    snippet: str
    score: float


class TestAnswerOut(BaseModel):
    answer: str
    spoken_text: str
    sources: list[SourceRef]
    confidence: Literal["high", "medium", "low"]
    fallback: bool
    latency_ms: dict[str, float]
    cache_hit: bool = False
    error: str | None = None
