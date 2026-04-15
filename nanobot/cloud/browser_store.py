"""Redis-backed browser control-plane store."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Protocol

from nanobot.cloud.browser_protocol import (
    AuthRealmMeta,
    BrowserEvent,
    BrowserJob,
    BrowserSessionMeta,
    derive_realm_key,
)
from nanobot.cloud.browser_protocol import auth_realm_id as make_auth_realm_id


class BrowserStore(Protocol):
    async def append_job(self, job: BrowserJob) -> str: ...
    async def append_event(self, event: BrowserEvent) -> str: ...
    async def save_task(self, task_id: str, data: dict[str, Any], ttl_s: int | None = None) -> None: ...
    async def get_task(self, task_id: str) -> dict[str, str] | None: ...
    async def save_session_meta(self, meta: BrowserSessionMeta, ttl_s: int | None = None) -> None: ...
    async def get_session_meta(self, browser_session_id: str) -> BrowserSessionMeta | None: ...
    async def save_auth_realm(self, meta: AuthRealmMeta, ttl_s: int | None = None) -> None: ...
    async def get_auth_realm(self, auth_realm_id: str) -> AuthRealmMeta | None: ...
    async def list_auth_realms(self, user_id: str) -> list[AuthRealmMeta]: ...
    async def save_auth_state(self, auth_realm_id: str, data: bytes, ttl_s: int) -> None: ...
    async def load_auth_state(self, auth_realm_id: str) -> bytes | None: ...
    async def save_media(
        self,
        media_id: str,
        *,
        data: bytes,
        content_type: str,
        filename: str,
        owner_user_id: str,
        browser_session_id: str,
        ttl_s: int,
    ) -> None: ...
    async def load_media(self, media_id: str) -> dict[str, Any] | None: ...


@dataclass(slots=True)
class BrowserKeyspace:
    prefix: str
    job_stream: str
    event_stream: str

    @classmethod
    def build(cls, base_prefix: str) -> "BrowserKeyspace":
        prefix = base_prefix.rstrip(":")
        return cls(
            prefix=prefix,
            job_stream=f"{prefix}:jobs",
            event_stream=f"{prefix}:events",
        )

    def task(self, task_id: str) -> str:
        return f"{self.prefix}:task:{task_id}"

    def session_meta(self, browser_session_id: str) -> str:
        return f"{self.prefix}:session:{browser_session_id}:meta"

    def auth_realm_set(self, user_id: str) -> str:
        return f"{self.prefix}:user:{user_id}:auth_realms"

    def auth_realm_meta(self, auth_realm: str) -> str:
        return f"{self.prefix}:realm:{auth_realm}:meta"

    def auth_state(self, auth_realm: str) -> str:
        return f"{self.prefix}:secret:auth:{auth_realm}"

    def media_meta(self, media_id: str) -> str:
        return f"{self.prefix}:secret:media:{media_id}:meta"

    def media_bytes(self, media_id: str) -> str:
        return f"{self.prefix}:secret:media:{media_id}:bytes"


class InMemoryBrowserStore:
    """In-memory browser store used by tests and local scaffolding."""

    def __init__(self, *, key_prefix: str = "nb:browser"):
        self.keys = BrowserKeyspace.build(key_prefix)
        self.jobs: list[tuple[str, dict[str, str]]] = []
        self.events: list[tuple[str, dict[str, str]]] = []
        self.tasks: dict[str, dict[str, str]] = {}
        self.sessions: dict[str, BrowserSessionMeta] = {}
        self.auth_realms: dict[str, AuthRealmMeta] = {}
        self.auth_realms_by_user: dict[str, set[str]] = {}
        self.auth_states: dict[str, tuple[bytes, float | None]] = {}
        self.media: dict[str, tuple[dict[str, str], bytes, float | None]] = {}
        self._counter = 0

    def _stream_id(self) -> str:
        self._counter += 1
        return f"{int(time.time() * 1000)}-{self._counter}"

    async def append_job(self, job: BrowserJob) -> str:
        stream_id = self._stream_id()
        self.jobs.append((stream_id, job.to_stream_fields()))
        return stream_id

    async def append_event(self, event: BrowserEvent) -> str:
        stream_id = self._stream_id()
        self.events.append((stream_id, event.to_stream_fields()))
        return stream_id

    async def save_task(self, task_id: str, data: dict[str, Any], ttl_s: int | None = None) -> None:
        serialized = {k: _serialize_scalar(v) for k, v in data.items()}
        if ttl_s is not None:
            serialized["_ttl_s"] = str(ttl_s)
        self.tasks[task_id] = serialized

    async def get_task(self, task_id: str) -> dict[str, str] | None:
        data = self.tasks.get(task_id)
        return dict(data) if data is not None else None

    async def save_session_meta(self, meta: BrowserSessionMeta, ttl_s: int | None = None) -> None:
        self.sessions[meta.browser_session_id] = meta

    async def get_session_meta(self, browser_session_id: str) -> BrowserSessionMeta | None:
        return self.sessions.get(browser_session_id)

    async def save_auth_realm(self, meta: AuthRealmMeta, ttl_s: int | None = None) -> None:
        self.auth_realms[meta.auth_realm_id] = meta
        self.auth_realms_by_user.setdefault(meta.user_id, set()).add(meta.auth_realm_id)

    async def get_auth_realm(self, auth_realm_id: str) -> AuthRealmMeta | None:
        return self.auth_realms.get(auth_realm_id)

    async def list_auth_realms(self, user_id: str) -> list[AuthRealmMeta]:
        ids = sorted(self.auth_realms_by_user.get(user_id, set()))
        return [self.auth_realms[item] for item in ids if item in self.auth_realms]

    async def save_auth_state(self, auth_realm_id: str, data: bytes, ttl_s: int) -> None:
        expires_at = time.monotonic() + ttl_s if ttl_s > 0 else None
        self.auth_states[auth_realm_id] = (data, expires_at)

    async def load_auth_state(self, auth_realm_id: str) -> bytes | None:
        item = self.auth_states.get(auth_realm_id)
        if item is None:
            return None
        data, expires_at = item
        if expires_at is not None and expires_at <= time.monotonic():
            self.auth_states.pop(auth_realm_id, None)
            return None
        return data

    async def save_media(
        self,
        media_id: str,
        *,
        data: bytes,
        content_type: str,
        filename: str,
        owner_user_id: str,
        browser_session_id: str,
        ttl_s: int,
    ) -> None:
        expires_at = time.monotonic() + ttl_s if ttl_s > 0 else None
        self.media[media_id] = (
            {
                "content_type": content_type,
                "filename": filename,
                "owner_user_id": owner_user_id,
                "browser_session_id": browser_session_id,
            },
            data,
            expires_at,
        )

    async def load_media(self, media_id: str) -> dict[str, Any] | None:
        item = self.media.get(media_id)
        if item is None:
            return None
        meta, data, expires_at = item
        if expires_at is not None and expires_at <= time.monotonic():
            self.media.pop(media_id, None)
            return None
        return {**meta, "bytes": data}


class RedisBrowserStore:
    """Redis-backed browser store."""

    def __init__(self, client, *, key_prefix: str):
        self._client = client
        self.keys = BrowserKeyspace.build(key_prefix)

    async def append_job(self, job: BrowserJob) -> str:
        stream_id = await self._client.xadd(self.keys.job_stream, job.to_stream_fields())
        return _as_text(stream_id)

    async def append_event(self, event: BrowserEvent) -> str:
        stream_id = await self._client.xadd(self.keys.event_stream, event.to_stream_fields())
        return _as_text(stream_id)

    async def save_task(self, task_id: str, data: dict[str, Any], ttl_s: int | None = None) -> None:
        key = self.keys.task(task_id)
        mapping = {k: _serialize_scalar(v) for k, v in data.items()}
        if mapping:
            await self._client.hset(key, mapping=mapping)
        if ttl_s is not None and ttl_s > 0:
            await self._client.expire(key, ttl_s)

    async def get_task(self, task_id: str) -> dict[str, str] | None:
        data = await self._client.hgetall(self.keys.task(task_id))
        if not data:
            return None
        return { _as_text(k): _as_text(v) for k, v in data.items() }

    async def save_session_meta(self, meta: BrowserSessionMeta, ttl_s: int | None = None) -> None:
        key = self.keys.session_meta(meta.browser_session_id)
        await self._client.hset(key, mapping=meta.to_mapping())
        if ttl_s is not None and ttl_s > 0:
            await self._client.expire(key, ttl_s)

    async def get_session_meta(self, browser_session_id: str) -> BrowserSessionMeta | None:
        data = await self._client.hgetall(self.keys.session_meta(browser_session_id))
        if not data:
            return None
        return BrowserSessionMeta.from_mapping({ _as_text(k): _as_text(v) for k, v in data.items() })

    async def save_auth_realm(self, meta: AuthRealmMeta, ttl_s: int | None = None) -> None:
        meta_key = self.keys.auth_realm_meta(meta.auth_realm_id)
        await self._client.hset(meta_key, mapping=meta.to_mapping())
        await self._client.sadd(self.keys.auth_realm_set(meta.user_id), meta.auth_realm_id)
        if ttl_s is not None and ttl_s > 0:
            await self._client.expire(meta_key, ttl_s)

    async def get_auth_realm(self, auth_realm_id: str) -> AuthRealmMeta | None:
        data = await self._client.hgetall(self.keys.auth_realm_meta(auth_realm_id))
        if not data:
            return None
        return AuthRealmMeta.from_mapping({ _as_text(k): _as_text(v) for k, v in data.items() })

    async def list_auth_realms(self, user_id: str) -> list[AuthRealmMeta]:
        realm_ids = await self._client.smembers(self.keys.auth_realm_set(user_id))
        metas: list[AuthRealmMeta] = []
        for item in realm_ids:
            meta = await self.get_auth_realm(_as_text(item))
            if meta is not None:
                metas.append(meta)
        return sorted(metas, key=lambda meta: meta.auth_realm_id)

    async def save_auth_state(self, auth_realm_id: str, data: bytes, ttl_s: int) -> None:
        await self._client.set(self.keys.auth_state(auth_realm_id), data, ex=ttl_s)

    async def load_auth_state(self, auth_realm_id: str) -> bytes | None:
        data = await self._client.get(self.keys.auth_state(auth_realm_id))
        if data is None or isinstance(data, bytes):
            return data
        return str(data).encode("utf-8")

    async def save_media(
        self,
        media_id: str,
        *,
        data: bytes,
        content_type: str,
        filename: str,
        owner_user_id: str,
        browser_session_id: str,
        ttl_s: int,
    ) -> None:
        meta_key = self.keys.media_meta(media_id)
        bytes_key = self.keys.media_bytes(media_id)
        await self._client.hset(
            meta_key,
            mapping={
                "content_type": content_type,
                "filename": filename,
                "owner_user_id": owner_user_id,
                "browser_session_id": browser_session_id,
            },
        )
        await self._client.set(bytes_key, data, ex=ttl_s)
        await self._client.expire(meta_key, ttl_s)

    async def load_media(self, media_id: str) -> dict[str, Any] | None:
        meta_key = self.keys.media_meta(media_id)
        bytes_key = self.keys.media_bytes(media_id)
        meta = await self._client.hgetall(meta_key)
        if not meta:
            return None
        data = await self._client.get(bytes_key)
        if data is None:
            return None
        return {
            "content_type": _as_text(meta.get("content_type")),
            "filename": _as_text(meta.get("filename")),
            "owner_user_id": _as_text(meta.get("owner_user_id")),
            "browser_session_id": _as_text(meta.get("browser_session_id")),
            "bytes": data if isinstance(data, bytes) else str(data).encode("utf-8"),
        }


async def find_reusable_auth_realm(
    store: BrowserStore,
    *,
    user_id: str,
    url: str | None = None,
    issuer: str | None = None,
    configured_realm: str | None = None,
) -> AuthRealmMeta | None:
    realm_key = derive_realm_key(url=url, issuer=issuer, configured_realm=configured_realm)
    if realm_key:
        direct = await store.get_auth_realm(make_auth_realm_id(user_id, realm_key))
        if direct is not None and not direct.is_expired():
            return direct

    matches: list[AuthRealmMeta] = []
    for meta in await store.list_auth_realms(user_id):
        if meta.is_expired():
            continue
        if issuer and meta.issuer and meta.issuer.strip().lower() == issuer.strip().lower():
            return meta
        if meta.matches_url(url):
            matches.append(meta)

    matches.sort(key=lambda item: item.last_used_at or "", reverse=True)
    return matches[0] if matches else None


def _serialize_scalar(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _as_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)
