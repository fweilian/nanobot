"""Online session storage for stateless cloud mode."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from nanobot.utils.helpers import safe_filename


def session_filename(session_key: str) -> str:
    """Return the canonical session filename used by SessionManager."""
    return f"{safe_filename(session_key.replace(':', '_'))}.jsonl"


def session_file_path(workspace: Path, session_key: str) -> Path:
    """Return the local session file path for a workspace/session pair."""
    return workspace / "sessions" / session_filename(session_key)


class OnlineSessionStore(Protocol):
    """Abstract online session store."""

    async def load(self, session_key: str) -> bytes | None: ...

    async def save(self, session_key: str, data: bytes) -> None: ...

    async def delete(self, session_key: str) -> None: ...


class InMemorySessionStore:
    """In-memory session store used by tests."""

    def __init__(self):
        self._data: dict[str, bytes] = {}

    async def load(self, session_key: str) -> bytes | None:
        return self._data.get(session_key)

    async def save(self, session_key: str, data: bytes) -> None:
        self._data[session_key] = data

    async def delete(self, session_key: str) -> None:
        self._data.pop(session_key, None)


class RedisSessionStore:
    """Redis-backed online session store."""

    def __init__(self, client, *, key_prefix: str, ttl_s: int) -> None:
        self._client = client
        self._key_prefix = key_prefix.rstrip(":")
        self._ttl_s = ttl_s

    def _key(self, session_key: str) -> str:
        return f"{self._key_prefix}:session:{session_key}"

    async def load(self, session_key: str) -> bytes | None:
        data = await self._client.get(self._key(session_key))
        return data if data is None or isinstance(data, bytes) else str(data).encode("utf-8")

    async def save(self, session_key: str, data: bytes) -> None:
        await self._client.set(self._key(session_key), data, ex=self._ttl_s)

    async def delete(self, session_key: str) -> None:
        await self._client.delete(self._key(session_key))
