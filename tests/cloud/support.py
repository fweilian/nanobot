from __future__ import annotations

import time


class MemoryStore:
    """In-memory object store used by cloud tests."""

    def __init__(self):
        self.data: dict[str, bytes] = {}

    def exists(self, key: str) -> bool:
        return key in self.data

    def list_keys(self, prefix: str) -> list[str]:
        normalized = prefix.rstrip("/") + "/"
        return sorted(key for key in self.data if key.startswith(normalized))

    def get_bytes(self, key: str) -> bytes:
        return self.data[key]

    def put_bytes(self, key: str, data: bytes) -> None:
        self.data[key] = data

    def delete_prefix(self, prefix: str) -> None:
        normalized = prefix.rstrip("/") + "/"
        for key in [key for key in self.data if key.startswith(normalized)]:
            del self.data[key]


class InMemorySessionStore:
    def __init__(self):
        self.data: dict[str, bytes] = {}

    async def load(self, session_key: str) -> bytes | None:
        return self.data.get(session_key)

    async def save(self, session_key: str, data: bytes) -> None:
        self.data[session_key] = data

    async def delete(self, session_key: str) -> None:
        self.data.pop(session_key, None)


class InMemoryLockManager:
    def __init__(self):
        self.data: dict[str, tuple[str, float]] = {}

    def _prune(self):
        now = time.monotonic()
        for key in [key for key, (_, expires) in self.data.items() if expires <= now]:
            del self.data[key]

    async def acquire(self, scope: str, ttl_s: int) -> str | None:
        self._prune()
        if scope in self.data:
            return None
        token = f"token-{len(self.data)+1}"
        self.data[scope] = (token, time.monotonic() + ttl_s)
        return token

    async def release(self, scope: str, token: str) -> None:
        self._prune()
        current = self.data.get(scope)
        if current and current[0] == token:
            del self.data[scope]
