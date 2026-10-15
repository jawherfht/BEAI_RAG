"""Ingestion-worker settings."""

from functools import lru_cache

from pydantic import Field

from beai_rag_core.settings import CoreSettings


class WorkerSettings(CoreSettings):
    log_level: str = "INFO"
    worker_concurrency: int = Field(default=2, gt=0)
    retry_base_ms: int = Field(default=2000, gt=0)  # retries after 2 s, 8 s, 32 s
    docling_ocr: bool = True
    docling_artifacts_path: str | None = None
    max_pdf_pages: int = Field(default=2000, gt=0)
    recrawl_check_interval_s: int = Field(default=900, gt=0)
    contextual_concurrency: int = Field(default=4, gt=0)


@lru_cache
def get_settings() -> WorkerSettings:
    return WorkerSettings()
