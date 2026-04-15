"""Cloud configuration and workspace models."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def encrypt_data(data: str) -> str:
    """Encrypt secret data for storage in .env."""
    # TODO: implement encryption (e.g., Fernet, AWS KMS, etc.)
    return data


def decrypt_data(data: str) -> str:
    """Decrypt secret data from .env."""
    # TODO: implement decryption
    return data


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


class RedisSettings(BaseModel):
    """Redis settings for stateless multi-instance cloud mode."""

    url: str = "redis://127.0.0.1:6379/0"
    mode: Literal["single", "cluster", "auto"] = "single"
    key_prefix: str = "nanobot-cloud"
    session_ttl_s: int = 24 * 60 * 60
    lock_ttl_s: int = 5 * 60


class SkillCacheSettings(BaseModel):
    """Skill cache settings for request-scoped staging."""

    small_skill_max_bytes: int = 64 * 1024
    request_stage_budget_bytes: int = 8 * 1024 * 1024
    instance_stage_budget_bytes: int = 32 * 1024 * 1024
    redis_content_ttl_s: int = 24 * 60 * 60


class BrowserSettings(BaseModel):
    """Browser control-plane settings."""

    enabled: bool = True
    key_prefix: str = "browser"
    auth_ttl_s: int = 60 * 60
    task_ttl_s: int = 15 * 60
    qr_ttl_s: int = 2 * 60
    media_ttl_s: int = 3 * 60
    shm_root: str = "/dev/shm/nanobot-browser"


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
    redis: RedisSettings = Field(default_factory=RedisSettings)
    skill_cache: SkillCacheSettings = Field(default_factory=SkillCacheSettings)
    browser: BrowserSettings = Field(default_factory=BrowserSettings)
    s3: S3Settings

    @property
    def cache_root(self) -> Path:
        """Root local cache directory."""
        return self.local_cache_dir.expanduser().resolve()
