"""Distributed locking for stateless cloud mode."""

from __future__ import annotations

import secrets
import time
from typing import Protocol

from loguru import logger

try:
    from redis.exceptions import RedisError
except Exception:  # pragma: no cover - redis is an optional runtime dependency for import time
    RedisError = Exception


class CloudSessionLockedError(RuntimeError):
    """Raised when a write session is already being processed elsewhere."""

    def __init__(self, scope: str) -> None:
        super().__init__(scope)
        self.scope = scope


class DistributedLockManager(Protocol):
    """Abstract distributed lock manager."""

    async def acquire(self, scope: str, ttl_s: int) -> str | None: ...

    async def release(self, scope: str, token: str) -> None: ...


class InMemoryDistributedLockManager:
    """In-memory lock manager used by tests."""

    def __init__(self):
        self._locks: dict[str, tuple[str, float]] = {}

    def _prune(self) -> None:
        now = time.monotonic()
        for scope in [scope for scope, (_, expiry) in self._locks.items() if expiry <= now]:
            del self._locks[scope]

    async def acquire(self, scope: str, ttl_s: int) -> str | None:
        self._prune()
        if scope in self._locks:
            return None
        token = secrets.token_urlsafe(16)
        self._locks[scope] = (token, time.monotonic() + ttl_s)
        return token

    async def release(self, scope: str, token: str) -> None:
        self._prune()
        current = self._locks.get(scope)
        if current and current[0] == token:
            del self._locks[scope]


class RedisDistributedLockManager:
    """Redis-backed distributed lock manager."""

    _RELEASE_SCRIPT = """
    if redis.call('get', KEYS[1]) == ARGV[1] then
      return redis.call('del', KEYS[1])
    end
    return 0
    """

    def __init__(self, client, *, key_prefix: str) -> None:
        self._client = client
        self._key_prefix = key_prefix.rstrip(":")
        self._fallback = InMemoryDistributedLockManager()
        self._degraded = False

    def _key(self, scope: str) -> str:
        return f"{self._key_prefix}:lock:{scope}"

    def _mark_degraded(self, exc: Exception) -> None:
        if self._degraded:
            return
        self._degraded = True
        logger.warning(
            "Redis lock manager unavailable; falling back to in-memory locks for this process: {}",
            exc,
        )

    async def acquire(self, scope: str, ttl_s: int) -> str | None:
        try:
            token = secrets.token_urlsafe(16)
            acquired = await self._client.set(self._key(scope), token, nx=True, ex=ttl_s)
            return token if acquired else None
        except (RedisError, OSError) as exc:
            self._mark_degraded(exc)
            return await self._fallback.acquire(scope, ttl_s)

    async def release(self, scope: str, token: str) -> None:
        try:
            await self._client.eval(self._RELEASE_SCRIPT, 1, self._key(scope), token)
        except (RedisError, OSError) as exc:
            self._mark_degraded(exc)
            await self._fallback.release(scope, token)
