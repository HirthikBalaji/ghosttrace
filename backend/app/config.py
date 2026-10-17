"""12-factor settings (environment variables, prefix GT_). Safe defaults; no credentials in code."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GT_", env_file=".env", extra="ignore")

    env: str = Field("local", pattern="^(local|test|ci|production)$")
    falkordb_host: str = "localhost"
    falkordb_port: int = 6379
    falkordb_password: str | None = None
    query_timeout_ms: int = Field(2000, ge=10, le=60000)
    cors_origins: str = "http://localhost:5174,http://127.0.0.1:5174,http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080"
    # Demo-only auth: header X-GT-Demo-Token must equal this token. Fails closed if unset outside local.
    demo_token: str | None = None
    auth_mode: str = Field("demo_header", pattern="^(demo_header|disabled_local|oidc)$")
    oidc_issuer: str | None = None
    oidc_audience: str | None = None
    oidc_jwks_url: str | None = None
    oidc_jwks_json: str | None = None  # pinned JWKS document (air-gapped deployments, tests)
    oidc_algorithms: str = "RS256,ES256"
    oidc_roles_claim: str = "roles"
    oidc_workspaces_claim: str = "gt_workspaces"
    oidc_subject_claim: str = "sub"
    run_mode: str = Field("inline", pattern="^(inline|queue)$")  # queue: a separate worker process runs investigations
    require_four_eyes: bool = True  # an approver may not approve an investigation they created (oidc mode)
    llm_provider: str = Field("mock", pattern="^(mock|anthropic|openai_compatible)$")
    llm_endpoint: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    max_path_depth: int = Field(8, ge=1, le=12)
    max_paths: int = Field(200, ge=1, le=2000)
    planner_timeout_s: float = Field(20.0, gt=0, le=300)
    rate_limit_per_minute: int = Field(60, ge=1)
    log_level: str = "INFO"
    artifact_dir: str = "../.artifacts"


@lru_cache
def get_settings() -> Settings:
    return Settings()
