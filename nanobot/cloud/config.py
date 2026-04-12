"""Cloud configuration and workspace models."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def utc_now_iso() -> str:
    """Return an ISO8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


class ManagedProviderView(BaseModel):
    """User-visible view of the platform-managed provider."""

    provider: str
    model: str
    managed: bool = True


class CloudAgentConfig(BaseModel):
    """Per-agent cloud configuration."""

    name: str
    description: str = "Default cloud agent"
    skills: list[str] = Field(default_factory=list)
    temperature: float | None = None
    max_tokens: int | None = None
    context_window_tokens: int | None = None
    context_block_limit: int | None = None
    max_tool_iterations: int | None = None
    max_tool_result_chars: int | None = None
    provider_retry_mode: Literal["standard", "persistent"] | None = None
    reasoning_effort: str | None = None
    timezone: str | None = None
    unified_session: bool | None = None
    session_ttl_minutes: int | None = None
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class UserWorkspaceConfig(BaseModel):
    """Per-user workspace index stored in object storage."""

    schema_version: int = 1
    user_id: str
    default_agent: str = "default"
    providers: dict[str, ManagedProviderView]
    agents: dict[str, str]
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class S3Settings(BaseModel):
    """S3-compatible object store settings."""

    bucket: str
    prefix: str = ""
    endpoint_url: str | None = None
    region_name: str | None = None
    access_key_id: str | None = None
    secret_access_key: str | None = None


class AuthSettings(BaseModel):
    """OAuth/OIDC access token verification settings."""

    issuer: str | None = None
    audience: str | None = None
    jwks_url: str | None = None
    shared_secret: str | None = None
    algorithms: list[str] = Field(default_factory=lambda: ["RS256"])
    user_id_claim: str = "sub"


class CloudServiceSettings(BaseSettings):
    """Service settings loaded from .env / environment."""

    model_config = SettingsConfigDict(
        env_prefix="NANOBOT_CLOUD_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    nanobot_config_path: Path
    local_cache_dir: Path = Path(".nanobot-cloud")
    request_timeout: float = 120.0
    host: str = "127.0.0.1"
    port: int = 8890
    workspace_prefix: str = "workspaces"
    auth: AuthSettings
    s3: S3Settings

    @property
    def cache_root(self) -> Path:
        """Root local cache directory."""
        return self.local_cache_dir.expanduser().resolve()
