"""Settings shared by both services. Values come from environment variables only."""

from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Commands run from the repo root or from services/<name>; the closest .env wins.
# Real environment variables always override .env values.
ENV_FILES = ("../../.env", "../.env", ".env")

# Verbatim from the harrier-oss-v1 card (prompt "web_search_query"); see ADR 0001.
DEFAULT_QUERY_TEMPLATE = (
    "Instruct: Given a web search query, retrieve relevant passages that answer the query\n"
    "Query: {text}"
)


class CoreSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILES, env_file_encoding="utf-8", extra="ignore")

    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr | None = None
    qdrant_collection: str = "kb_chunks"
    qdrant_timeout_s: float = 5.0

    database_url: str = "postgresql+asyncpg://beai:beai@localhost:5432/beai_rag"
    redis_url: str = "redis://localhost:6379/0"
    rabbitmq_url: SecretStr = SecretStr("amqp://guest:guest@localhost:5672/")

    s3_endpoint: str = "http://localhost:9000"
    s3_bucket: str = "beai-kb"
    s3_access_key: SecretStr = SecretStr("minio")
    s3_secret_key: SecretStr = SecretStr("minio123")
    s3_region: str = "us-east-1"
    s3_timeout_s: float = 30.0

    # Embeddings (pluggable: swapping to the fallback model is a config change).
    embed_provider: Literal["tei", "vllm", "local"] = "tei"
    embed_url: str = "http://localhost:8080"
    embed_model: str = "microsoft/harrier-oss-v1-0.6b"
    embed_model_revision: str = "f9b9dc8d367d443f2479d27aa5d8d2850c0774ee"
    embed_dim: int = Field(default=1024, gt=0)
    # Query-side instruction required by the model card ({text} is replaced by the question).
    # Documents are embedded without any instruction. See docs/decisions/0001-models.md.
    embed_query_template: str = DEFAULT_QUERY_TEMPLATE
    embed_batch_size: int = Field(default=32, gt=0)
    embed_timeout_s: float = 60.0
    # Tokenizer used to measure chunk sizes in tokens; defaults to the embed model's.
    tokenizer_model: str | None = None
    sparse_model: str = "Qdrant/bm25"
    model_cache_dir: str | None = None

    # LLM (OpenAI-compatible). Used by generation (Phase 4) and contextual chunks.
    # Production: vLLM on the GPU pool. Dev: any OpenAI-compatible endpoint (e.g. Groq).
    llm_base_url: str = "http://localhost:8000/v1"
    llm_model: str = "Qwen/Qwen3.8-27B"
    # Leave unset when a gateway/proxy injects the Authorization header (no header is sent).
    llm_api_key: SecretStr | None = None
    llm_disable_thinking: bool = True
    # How the provider disables thinking: vLLM/SGLang use chat_template_kwargs.enable_thinking;
    # Groq uses reasoning_effort="none" (it rejects chat_template_kwargs). See ADR 0009.
    llm_thinking_switch: Literal["chat_template_kwargs", "reasoning_effort", "none"] = (
        "chat_template_kwargs"
    )
    llm_timeout_s: float = Field(default=30.0, gt=0)
    llm_max_retries: int = Field(default=4, ge=0)  # 429 / 5xx / connect errors before 1st token
    llm_retry_base_s: float = Field(default=1.0, gt=0)
    llm_retry_max_wait_s: float = Field(default=20.0, gt=0)
    llm_max_tokens: int = Field(default=200, gt=0)
    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    contextual_chunks: bool = False

    max_upload_mb: int = Field(default=50, gt=0)

    def llm_key(self) -> str | None:
        return self.llm_api_key.get_secret_value() if self.llm_api_key else None

    score_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
