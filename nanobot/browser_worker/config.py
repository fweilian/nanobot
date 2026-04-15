"""Browser worker configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from nanobot.cloud.config import CloudServiceSettings


class BrowserWorkerSettings(BaseSettings):
    """Settings for the standalone browser worker."""

    model_config = SettingsConfigDict(
        env_prefix="NANOBOT_BROWSER_WORKER_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    redis_url: str | None = None
    redis_mode: Literal["single", "cluster", "auto"] | None = None
    redis_key_prefix: str | None = None
    browser_key_prefix: str | None = None
    worker_id: str = "worker-1"
    poll_block_ms: int = 1000
    auth_ttl_s: int | None = None
    qr_ttl_s: int | None = None
    shm_root: Path | None = Field(default=None)

    @classmethod
    def load(cls) -> "BrowserWorkerSettings":
        """Load worker settings, falling back to cloud env when worker-specific env is absent."""
        current = cls()
        cloud: CloudServiceSettings | None = None
        try:
            cloud = CloudServiceSettings()
        except Exception:
            cloud = None

        return cls.model_construct(
            redis_url=current.redis_url or (cloud.redis.url if cloud else "redis://127.0.0.1:6379/0"),
            redis_mode=current.redis_mode or (cloud.redis.mode if cloud else "single"),
            redis_key_prefix=current.redis_key_prefix or (cloud.redis.key_prefix if cloud else "nanobot-cloud"),
            browser_key_prefix=current.browser_key_prefix or (cloud.browser.key_prefix if cloud else "browser"),
            worker_id=current.worker_id,
            poll_block_ms=current.poll_block_ms,
            auth_ttl_s=current.auth_ttl_s or (cloud.browser.auth_ttl_s if cloud else 3600),
            qr_ttl_s=current.qr_ttl_s or (cloud.browser.qr_ttl_s if cloud else 120),
            shm_root=current.shm_root or (cloud.browser.shm_root if cloud else Path("/dev/shm/nanobot-browser")),
        )
