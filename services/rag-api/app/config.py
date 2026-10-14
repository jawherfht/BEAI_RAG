"""rag-api settings (pydantic-settings). Every value comes from the environment."""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import NoDecode

from beai_rag_core.settings import CoreSettings


class Settings(CoreSettings):
    app_name: str = "beai-rag-api"
    environment: Literal["dev", "test", "staging", "prod"] = "dev"
    log_level: str = "INFO"

    # Auth: the API Gateway forwards a JWT (Bearer) or an API key.
    jwt_algorithms: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["RS256"])
    jwt_public_key: SecretStr | None = None  # PEM, for RS256/ES256 tokens from the gateway
    jwt_secret: SecretStr | None = None  # HS256, dev/test only
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    jwt_tenant_claim: str = "tenant_id"
    jwt_agents_claim: str = "agents"
    # JSON object: {"<sha256 of key>": {"tenant_id": "<uuid>", "agents": ["<uuid>", ...]}}
    api_keys: SecretStr | None = None

    # Bootstrapping of dev infrastructure at startup.
    qdrant_auto_create: bool = True
    s3_auto_create_bucket: bool = True
    readiness_timeout_s: float = 2.0

    # Model/serving settings (used from Phase 2 on; declared now so config is complete).
    embed_provider: Literal["tei", "vllm", "local"] = "tei"
    embed_url: str = "http://localhost:8080"
    rerank_url: str = "http://localhost:8081"
    rerank_model: str = "Qwen/Qwen3-Reranker-0.6B"
    llm_base_url: str = "http://localhost:8000/v1"
    llm_model: str = "Qwen3.8-27B"
    llm_api_key: SecretStr = SecretStr("not-needed-locally")
    llm_disable_thinking: bool = True
    llm_max_tokens: int = Field(default=200, gt=0)
    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)

    score_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    conf_high: float = Field(default=0.70, ge=0.0, le=1.0)
    conf_mid: float = Field(default=0.55, ge=0.0, le=1.0)
    contextual_chunks: bool = False
    answer_cache_ttl_s: int = Field(default=86400, gt=0)
    max_upload_mb: int = Field(default=50, gt=0)
    langfuse_host: str | None = None

    @field_validator("jwt_algorithms", mode="before")
    @classmethod
    def _split_algorithms(cls, v: object) -> object:
        if isinstance(v, str):
            return [a.strip() for a in v.strip("[]").replace('"', "").split(",") if a.strip()]
        return v

    @model_validator(mode="after")
    def _check(self) -> "Settings":
        if not self.score_threshold <= self.conf_mid <= self.conf_high:
            raise ValueError("thresholds must satisfy SCORE_THRESHOLD <= CONF_MID <= CONF_HIGH")
        if self.environment == "prod" and self.jwt_secret is not None:
            raise ValueError("JWT_SECRET (HS256) is for dev/test only; use JWT_PUBLIC_KEY in prod")
        if any(a.startswith("HS") for a in self.jwt_algorithms) and self.jwt_secret is None:
            raise ValueError("HS* algorithms require JWT_SECRET")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
