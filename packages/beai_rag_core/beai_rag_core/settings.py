"""Settings shared by both services. Values come from environment variables only."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Commands run from the repo root or from services/<name>; the closest .env wins.
# Real environment variables always override .env values.
ENV_FILES = ("../../.env", "../.env", ".env")


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

    embed_model: str = "microsoft/harrier-oss-v1-0.6b"
    embed_dim: int = Field(default=1024, gt=0)
    sparse_model: str = "Qdrant/bm25"
