"""Knowledge metadata tables (spec section 4.1)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from beai_rag_core.enums import (
    Confidence,
    JobKind,
    JobStatus,
    KnowledgeBaseStatus,
    SourceStatus,
    SourceType,
)

DEFAULT_FALLBACK_MESSAGE = "I'm not sure about that. Would you like me to connect you with someone?"

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def pg_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    return Enum(
        enum_cls,
        name=name,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class KnowledgeBase(TimestampMixin, Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = (
        UniqueConstraint("tenant_id", "agent_id", name="uq_knowledge_bases_tenant_agent"),
        CheckConstraint(
            "chunk_size BETWEEN 200 AND 1000 AND (chunk_size % 50 = 0 OR chunk_size = 512)",
            name="chunk_size_range",
        ),
        CheckConstraint("chunk_overlap >= 0 AND chunk_overlap < chunk_size", name="chunk_overlap"),
        CheckConstraint("top_k BETWEEN 1 AND 10", name="top_k_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[KnowledgeBaseStatus] = mapped_column(
        pg_enum(KnowledgeBaseStatus, "kb_status"),
        default=KnowledgeBaseStatus.EMPTY,
        server_default=KnowledgeBaseStatus.EMPTY.value,
        nullable=False,
    )
    rag_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    chunk_size: Mapped[int] = mapped_column(
        Integer, default=512, server_default="512", nullable=False
    )
    chunk_overlap: Mapped[int] = mapped_column(
        Integer, default=64, server_default="64", nullable=False
    )
    top_k: Mapped[int] = mapped_column(Integer, default=4, server_default="4", nullable=False)
    score_threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    fallback_message: Mapped[str] = mapped_column(
        Text,
        default=DEFAULT_FALLBACK_MESSAGE,
        server_default=DEFAULT_FALLBACK_MESSAGE,
        nullable=False,
    )
    hybrid_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    rerank_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    embed_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    embed_model_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    kb_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)

    sources: Mapped[list[Source]] = relationship(
        back_populates="knowledge_base", cascade="all, delete-orphan"
    )


class Source(TimestampMixin, Base):
    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint("crawl_depth BETWEEN 0 AND 3", name="crawl_depth_range"),
        CheckConstraint("max_pages BETWEEN 1 AND 500", name="max_pages_range"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    type: Mapped[SourceType] = mapped_column(pg_enum(SourceType, "source_type"), nullable=False)
    file_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    crawl_depth: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    max_pages: Mapped[int] = mapped_column(Integer, default=50, server_default="50", nullable=False)
    recrawl_interval_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    status: Mapped[SourceStatus] = mapped_column(
        pg_enum(SourceStatus, "source_status"),
        default=SourceStatus.QUEUED,
        server_default=SourceStatus.QUEUED.value,
        nullable=False,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    pages: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    knowledge_base: Mapped[KnowledgeBase] = relationship(back_populates="sources")
    jobs: Mapped[list[IngestionJob]] = relationship(
        back_populates="source", cascade="all, delete-orphan"
    )


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[JobKind] = mapped_column(pg_enum(JobKind, "job_kind"), nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        pg_enum(JobStatus, "job_status"),
        default=JobStatus.QUEUED,
        server_default=JobStatus.QUEUED.value,
        nullable=False,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    source: Mapped[Source] = relationship(back_populates="jobs")


class AnswerLog(Base):
    """Sampled, PII-scrubbed answer log for analytics and eval mining."""

    __tablename__ = "answers_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]", nullable=False
    )
    confidence: Mapped[Confidence] = mapped_column(
        pg_enum(Confidence, "confidence"), nullable=False
    )
    fallback: Mapped[bool] = mapped_column(Boolean, nullable=False)
    latency_ms: Mapped[dict[str, float]] = mapped_column(
        JSONB, default=dict, server_default="{}", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False
    )
