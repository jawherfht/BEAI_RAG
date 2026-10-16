"""rag-api settings (pydantic-settings). Every value comes from the environment."""

import json
from functools import lru_cache
from pathlib import Path
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

    # Model/serving settings shared with the worker live in CoreSettings.
    rerank_provider: Literal["local", "vllm", "none"] = "local"
    rerank_url: str = "http://localhost:8080"  # embed-server serves /rerank in dev
    rerank_model: str = "Qwen/Qwen3-Reranker-0.6B"
    rerank_instruction: str = (
        "Given a web search query, retrieve relevant passages that answer the query"
    )
    rerank_timeout_s: float = 30.0
    rerank_candidates: int = Field(default=50, gt=0)
    rerank_min_candidates: int = Field(default=10, gt=0)  # skip re-ranking below this
    # Re-ranker scores are P(yes) in [0, 1]: their own thresholds (placeholders -> calibrate).
    rerank_score_threshold: float = Field(default=0.30, ge=0.0, le=1.0)
    rerank_conf_mid: float = Field(default=0.50, ge=0.0, le=1.0)
    rerank_conf_high: float = Field(default=0.80, ge=0.0, le=1.0)

    llm_max_input_tokens: int = Field(default=2500, gt=200)  # prompt budget (TTFT)
    readiness_check_llm: bool = True
    answer_log_sample_rate: float = Field(default=0.1, ge=0.0, le=1.0)
    answer_log_retention_days: int = Field(default=30, gt=0)

    # gRPC for the Interaction Agents Service. Tenant metadata is trusted only over mTLS.
    grpc_enabled: bool = True
    grpc_host: str = "0.0.0.0"  # noqa: S104 - container listens on all interfaces
    grpc_port: int = 50051
    grpc_tls_cert: str | None = None
    grpc_tls_key: str | None = None
    grpc_client_ca: str | None = None
    grpc_allow_insecure: bool = False

    search_prefetch_limit: int = Field(default=50, gt=0)
    search_hnsw_ef: int = Field(default=128, gt=0)
    readiness_check_reranker: bool = False

    conf_high: float = Field(default=0.70, ge=0.0, le=1.0)
    conf_mid: float = Field(default=0.55, ge=0.0, le=1.0)
    answer_cache_ttl_s: int = Field(default=86400, gt=0)
    max_files_per_upload: int = Field(default=20, gt=0)
    # Zip-based uploads (DOCX/PPTX): limits against zip bombs.
    max_zip_uncompressed_mb: int = Field(default=500, gt=0)
    max_zip_entries: int = Field(default=10000, gt=0)
    langfuse_host: str | None = None

    @field_validator("jwt_algorithms", mode="before")
    @classmethod
    def _split_algorithms(cls, v: object) -> object:
        if isinstance(v, str):
            return [a.strip() for a in v.strip("[]").replace('"', "").split(",") if a.strip()]
        return v

    # Calibrated thresholds (eval/calibrate.py). Default: config/thresholds.<embed model>.json,
    # looked up from the working directory upwards. Explicit env values still win.
    thresholds_file: str | None = None
    thresholds_source: str = "defaults"

    @model_validator(mode="after")
    def _load_thresholds(self) -> "Settings":
        path = _find_thresholds_file(self.thresholds_file, self.embed_model)
        if path is None:
            return self
        data = json.loads(path.read_text())
        if data.get("embed_model") not in (None, self.embed_model):
            return self  # calibrated for another model: ignore
        for key in ("score_threshold", "conf_mid", "conf_high"):
            if key not in self.model_fields_set and key in data:
                object.__setattr__(self, key, float(data[key]))
        object.__setattr__(self, "thresholds_source", str(path))
        return self

    @model_validator(mode="after")
    def _check(self) -> "Settings":
        if not self.score_threshold <= self.conf_mid <= self.conf_high:
            raise ValueError("thresholds must satisfy SCORE_THRESHOLD <= CONF_MID <= CONF_HIGH")
        if not self.rerank_score_threshold <= self.rerank_conf_mid <= self.rerank_conf_high:
            raise ValueError("re-ranker thresholds must be ordered like the dense ones")
        if self.environment == "prod" and self.jwt_secret is not None:
            raise ValueError("JWT_SECRET (HS256) is for dev/test only; use JWT_PUBLIC_KEY in prod")
        if any(a.startswith("HS") for a in self.jwt_algorithms):
            if self.jwt_secret is None:
                raise ValueError("HS* algorithms require JWT_SECRET")
            if len(self.jwt_secret.get_secret_value().encode()) < 32:
                raise ValueError("JWT_SECRET must be at least 32 bytes (RFC 7518 3.2)")
        return self


def _find_thresholds_file(explicit: str | None, embed_model: str) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else None
    name = f"thresholds.{embed_model.rsplit('/', 1)[-1]}.json"
    here = Path.cwd()
    for folder in (here, *here.parents[:3]):
        candidate = folder / "config" / name
        if candidate.is_file():
            return candidate
    return None


@lru_cache
def get_settings() -> Settings:
    return Settings()
