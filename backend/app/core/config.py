"""Application configuration.

All configuration is read from environment variables (optionally via a local `.env`
file that is git-ignored). Secrets are typed as `SecretStr` so they are never
rendered in logs, reprs, or API responses.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_DIR = BACKEND_DIR.parent

AppEnv = Literal["local", "demo", "test", "staging", "production"]

# Placeholder values that must never be used outside local/demo/test environments.
INSECURE_PLACEHOLDERS = {
    "",
    "change-me",
    "changeme",
    "replace-with-a-long-random-secret",
    "dev-secret",
    "secret",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_DIR / ".env"), str(BACKEND_DIR / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Environment -------------------------------------------------------
    app_env: AppEnv = "local"
    demo_mode: bool = True
    app_name: str = "BankOps AI Command Center"
    expose_api_docs: bool = True

    # --- Database ----------------------------------------------------------
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'bankops_demo.db').as_posix()}"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_echo: bool = False

    # --- Authentication ----------------------------------------------------
    jwt_secret: SecretStr | None = None
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    jwt_issuer: str = "bankops-ai-command-center"
    jwt_audience: str = "bankops-ui"
    access_token_ttl_minutes: int = Field(default=30, ge=5, le=120)
    # Local-only demo password used by the seed script. Never used in production.
    demo_password: SecretStr | None = None

    # --- HTTP hardening ----------------------------------------------------
    cors_allowed_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    max_request_body_bytes: int = 1_048_576
    max_upload_bytes: int = 2_097_152
    rate_limit_per_minute: int = 240
    login_rate_limit_per_minute: int = 10

    # --- Model gateway -----------------------------------------------------
    llm_provider: Literal["mock", "openai_compatible"] = "mock"
    llm_base_url: str | None = None
    llm_api_key: SecretStr | None = None
    llm_model: str = "gpt-4o-mini"
    llm_approved_models: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["gpt-4o-mini", "gpt-4.1-mini"]
    )
    llm_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    llm_max_retries: int = Field(default=2, ge=0, le=5)
    llm_circuit_breaker_threshold: int = Field(default=3, ge=1, le=20)
    llm_circuit_breaker_cooldown_seconds: float = Field(default=60.0, ge=1, le=3600)
    llm_max_output_tokens: int = Field(default=1200, ge=64, le=8000)
    llm_judge_enabled: bool = False

    embedding_provider: Literal["hashing", "openai_compatible"] = "hashing"
    embedding_model: str = "text-embedding-3-small"
    embedding_base_url: str | None = None
    embedding_api_key: SecretStr | None = None
    embedding_dim: int = Field(default=384, ge=64, le=2048)

    # Cost estimates (USD per 1K tokens). Labeled as estimates everywhere.
    cost_per_1k_input_tokens: float = 0.00015
    cost_per_1k_output_tokens: float = 0.0006

    # --- RAG -----------------------------------------------------------------
    chunk_size: int = Field(default=900, ge=200, le=4000)
    chunk_overlap: int = Field(default=150, ge=0, le=1000)
    retrieval_top_k: int = Field(default=6, ge=1, le=20)
    retrieval_min_score: float = Field(default=0.12, ge=0.0, le=1.0)
    retrieval_max_candidates: int = Field(default=2000, ge=10, le=20000)
    retrieval_mode: Literal["hybrid", "semantic", "keyword"] = "hybrid"
    reranker: Literal["none", "lexical"] = "lexical"

    # --- Workflow bounds -----------------------------------------------------
    workflow_max_steps: int = Field(default=16, ge=4, le=64)
    workflow_max_tool_calls: int = Field(default=30, ge=1, le=200)
    workflow_token_budget: int = Field(default=60000, ge=1000, le=1_000_000)
    workflow_step_timeout_seconds: float = Field(default=45.0, gt=0, le=600)
    workflow_total_timeout_seconds: float = Field(default=300.0, gt=0, le=3600)
    workflow_execution_mode: Literal["background", "sync"] = "background"
    workflow_worker_threads: int = Field(default=2, ge=1, le=8)
    tool_timeout_seconds: float = Field(default=10.0, gt=0, le=120)

    # --- Policy --------------------------------------------------------------
    approval_ttl_minutes: int = Field(default=60, ge=1, le=1440)
    medium_risk_requires_approval: bool = True
    low_risk_requires_approval: bool = False
    allow_self_approval_medium: bool = False

    # --- Retention (days) ------------------------------------------------------
    retention_investigations_days: int = 90
    retention_deleted_documents_days: int = 30
    retention_audit_days: int = 2555

    # --- Seeding -------------------------------------------------------------
    seed_on_startup: bool = False

    @field_validator("cors_allowed_origins", "llm_approved_models", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                return json.loads(stripped)
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value

    @field_validator("database_url")
    @classmethod
    def _absolute_sqlite_path(cls, value: str) -> str:
        """Resolve relative SQLite paths against the repository root so every entry point agrees."""
        prefix = "sqlite:///"
        if value.startswith(prefix) and not value.endswith(":memory:"):
            path = Path(value[len(prefix):])
            if not path.is_absolute():
                return prefix + (REPO_DIR / path).resolve().as_posix()
        return value

    # ------------------------------------------------------------------------
    @property
    def is_production_like(self) -> bool:
        return self.app_env in ("staging", "production")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def vector_backend(self) -> str:
        return "sqlite-python-cosine" if self.is_sqlite else "pgvector"

    @property
    def index_version(self) -> str:
        """Identifies the embedding + chunking configuration used for indexing.

        Any change to embedding provider/model/dimension or chunking parameters
        produces a new index version and marks existing chunks as stale.
        """
        model = self.embedding_model if self.embedding_provider != "hashing" else "fh-v1"
        raw = f"{self.embedding_provider}:{model}:{self.embedding_dim}:{self.chunk_size}:{self.chunk_overlap}"
        return f"idx-{hashlib.sha256(raw.encode()).hexdigest()[:10]}"

    @property
    def model_mode(self) -> str:
        return "MOCK" if self.llm_provider == "mock" else "LIVE"


_EPHEMERAL_SECRET = secrets.token_urlsafe(48)


def resolve_jwt_secret(settings: Settings) -> str:
    """Return the signing secret.

    Local/demo/test environments may run without an explicit secret; an
    ephemeral random secret is generated per process (tokens become invalid on
    restart). Production-like environments must provide a strong secret; this is
    enforced by `validate_startup_settings`.
    """
    if settings.jwt_secret is not None and settings.jwt_secret.get_secret_value():
        return settings.jwt_secret.get_secret_value()
    return _EPHEMERAL_SECRET


class InsecureConfigurationError(RuntimeError):
    """Raised when the service is started with configuration unsafe for its environment."""


def validate_startup_settings(settings: Settings) -> list[str]:
    """Validate configuration before serving traffic.

    Returns a list of warnings. Raises `InsecureConfigurationError` in
    production-like environments when the configuration is unsafe.
    """
    warnings: list[str] = []
    problems: list[str] = []
    secret = settings.jwt_secret.get_secret_value() if settings.jwt_secret else ""

    if settings.is_production_like:
        if settings.demo_mode:
            problems.append("DEMO_MODE must be false in staging/production.")
        if settings.demo_password is not None:
            problems.append("DEMO_PASSWORD must not be set in staging/production (demo accounts are local-only).")
        if secret.strip().lower() in INSECURE_PLACEHOLDERS or len(secret) < 32:
            problems.append("JWT_SECRET must be set to a random value of at least 32 characters.")
        if any(origin.strip() == "*" for origin in settings.cors_allowed_origins):
            problems.append("CORS_ALLOWED_ORIGINS must not contain '*'.")
        if settings.is_sqlite:
            problems.append("SQLite is a local fallback only; use PostgreSQL + pgvector in staging/production.")
        if settings.seed_on_startup:
            problems.append("SEED_ON_STARTUP must be false in staging/production.")
    else:
        if not secret:
            warnings.append("JWT_SECRET not set: using an ephemeral per-process secret (local/demo only).")
        if settings.is_sqlite:
            warnings.append("Using SQLite fallback with in-process cosine similarity (see docs/DECISIONS.md).")

    if settings.llm_provider == "openai_compatible":
        if settings.llm_model not in settings.llm_approved_models:
            problems.append(
                f"LLM_MODEL '{settings.llm_model}' is not in LLM_APPROVED_MODELS; refusing to use an unapproved model."
            )
        if not settings.llm_base_url or settings.llm_api_key is None:
            problems.append("LLM_PROVIDER=openai_compatible requires LLM_BASE_URL and LLM_API_KEY.")

    if problems and (settings.is_production_like or settings.llm_provider == "openai_compatible"):
        raise InsecureConfigurationError("; ".join(problems))
    warnings.extend(problems)
    return warnings


@lru_cache
def get_settings() -> Settings:
    return Settings()
