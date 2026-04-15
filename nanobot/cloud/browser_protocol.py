"""Browser control-plane protocol types and helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from fnmatch import fnmatch
from typing import Any
from urllib.parse import urlsplit


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def browser_session_id(
    user_id: str,
    agent_name: str,
    session_id: str,
    tab_id: str | None = None,
) -> str:
    base = f"cloud:{user_id}:{agent_name}:{session_id}:browser"
    return f"{base}:{tab_id}" if tab_id else base


def auth_realm_id(user_id: str, realm_key: str) -> str:
    return f"{user_id}:{realm_key.strip().lower()}"


def _normalized_host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return (urlsplit(url).hostname or "").strip().lower() or None
    except Exception:
        return None


def derive_realm_key(
    *,
    url: str | None = None,
    issuer: str | None = None,
    configured_realm: str | None = None,
) -> str | None:
    if configured_realm:
        return configured_realm.strip().lower() or None
    host = _normalized_host(issuer)
    if host:
        return host
    return _normalized_host(url)


class BrowserAction(StrEnum):
    OPEN_URL = "open_url"
    BEGIN_LOGIN = "begin_login"
    WAIT_FOR_LOGIN = "wait_for_login"
    RESOLVE_AUTH_REALM = "resolve_auth_realm"
    NAVIGATE = "navigate"
    CLICK = "click"
    FILL = "fill"
    EXTRACT = "extract"
    SCREENSHOT = "screenshot"
    CLOSE_SESSION = "close_session"


class BrowserEventType(StrEnum):
    ACCEPTED = "accepted"
    CLAIMED = "claimed"
    STARTED = "started"
    PROGRESS = "progress"
    QR_READY = "qr_ready"
    AWAITING_USER = "awaiting_user"
    AUTH_REALM_RESOLVED = "auth_realm_resolved"
    AUTH_REALM_REUSED = "auth_realm_reused"
    LOGIN_SUCCESS = "login_success"
    LOGIN_FAILED = "login_failed"
    EXTRACT_READY = "extract_ready"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class BrowserSessionState(StrEnum):
    IDLE = "idle"
    BOOTING = "booting"
    READY = "ready"
    AUTH_REALM_RESOLVING = "auth_realm_resolving"
    AWAITING_LOGIN = "awaiting_login"
    AUTHENTICATED = "authenticated"
    BUSY = "busy"
    CLOSING = "closing"
    EXPIRED = "expired"
    FAILED = "failed"


@dataclass(slots=True)
class AuthRealmMeta:
    user_id: str
    auth_realm_id: str
    realm_key: str
    issuer: str | None = None
    domain_patterns: list[str] = field(default_factory=list)
    auth_version: int = 1
    expires_at: str | None = None
    last_validated_at: str | None = None
    last_used_at: str | None = None

    def matches_url(self, url: str | None) -> bool:
        host = _normalized_host(url)
        if not host:
            return False
        if self.issuer and _normalized_host(self.issuer) == host:
            return True
        for pattern in self.domain_patterns:
            normalized = pattern.strip().lower()
            if not normalized:
                continue
            if normalized.startswith(".") and (host == normalized[1:] or host.endswith(normalized)):
                return True
            if fnmatch(host, normalized):
                return True
            if normalized == host:
                return True
        return False

    def is_expired(self, *, now: datetime | None = None) -> bool:
        if not self.expires_at:
            return False
        try:
            current = now or datetime.now(timezone.utc)
            expires = datetime.fromisoformat(self.expires_at)
            return expires <= current
        except ValueError:
            return False

    def to_mapping(self) -> dict[str, str]:
        return {
            "user_id": self.user_id,
            "auth_realm_id": self.auth_realm_id,
            "realm_key": self.realm_key,
            "issuer": self.issuer or "",
            "domain_patterns": json.dumps(self.domain_patterns, ensure_ascii=False),
            "auth_version": str(self.auth_version),
            "expires_at": self.expires_at or "",
            "last_validated_at": self.last_validated_at or "",
            "last_used_at": self.last_used_at or "",
        }

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "AuthRealmMeta":
        domain_patterns_raw = data.get("domain_patterns", "[]")
        if isinstance(domain_patterns_raw, bytes):
            domain_patterns_raw = domain_patterns_raw.decode("utf-8")
        if isinstance(domain_patterns_raw, str):
            try:
                domain_patterns = json.loads(domain_patterns_raw)
            except json.JSONDecodeError:
                domain_patterns = [domain_patterns_raw]
        else:
            domain_patterns = list(domain_patterns_raw or [])
        return cls(
            user_id=_to_text(data.get("user_id")),
            auth_realm_id=_to_text(data.get("auth_realm_id")),
            realm_key=_to_text(data.get("realm_key")),
            issuer=_optional_text(data.get("issuer")),
            domain_patterns=[str(item) for item in domain_patterns],
            auth_version=int(_to_text(data.get("auth_version", "1")) or "1"),
            expires_at=_optional_text(data.get("expires_at")),
            last_validated_at=_optional_text(data.get("last_validated_at")),
            last_used_at=_optional_text(data.get("last_used_at")),
        )


@dataclass(slots=True)
class BrowserSessionMeta:
    browser_session_id: str
    user_id: str
    agent_name: str
    chat_session_id: str
    auth_realm_id: str | None = None
    owner_worker_id: str | None = None
    lease_expires_at: str | None = None
    status: str = BrowserSessionState.IDLE
    current_url: str | None = None
    auth_state_ref: str | None = None
    profile_snapshot_ref: str | None = None
    last_task_id: str | None = None
    last_event_id: str | None = None
    updated_at: str = field(default_factory=utc_now_iso)

    def to_mapping(self) -> dict[str, str]:
        return {
            "browser_session_id": self.browser_session_id,
            "user_id": self.user_id,
            "agent_name": self.agent_name,
            "chat_session_id": self.chat_session_id,
            "auth_realm_id": self.auth_realm_id or "",
            "owner_worker_id": self.owner_worker_id or "",
            "lease_expires_at": self.lease_expires_at or "",
            "status": str(self.status),
            "current_url": self.current_url or "",
            "auth_state_ref": self.auth_state_ref or "",
            "profile_snapshot_ref": self.profile_snapshot_ref or "",
            "last_task_id": self.last_task_id or "",
            "last_event_id": self.last_event_id or "",
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "BrowserSessionMeta":
        return cls(
            browser_session_id=_to_text(data.get("browser_session_id")),
            user_id=_to_text(data.get("user_id")),
            agent_name=_to_text(data.get("agent_name")),
            chat_session_id=_to_text(data.get("chat_session_id")),
            auth_realm_id=_optional_text(data.get("auth_realm_id")),
            owner_worker_id=_optional_text(data.get("owner_worker_id")),
            lease_expires_at=_optional_text(data.get("lease_expires_at")),
            status=_to_text(data.get("status", BrowserSessionState.IDLE)),
            current_url=_optional_text(data.get("current_url")),
            auth_state_ref=_optional_text(data.get("auth_state_ref")),
            profile_snapshot_ref=_optional_text(data.get("profile_snapshot_ref")),
            last_task_id=_optional_text(data.get("last_task_id")),
            last_event_id=_optional_text(data.get("last_event_id")),
            updated_at=_to_text(data.get("updated_at", utc_now_iso())),
        )


@dataclass(slots=True)
class BrowserJob:
    job_id: str
    task_id: str
    browser_session_id: str
    user_id: str
    agent_name: str
    chat_session_id: str
    action: str
    payload: dict[str, Any] = field(default_factory=dict)
    auth_realm_id: str | None = None
    idempotency_key: str | None = None
    reply_stream: str = ""
    created_at: str = field(default_factory=utc_now_iso)
    timeout_s: int = 120

    def to_stream_fields(self) -> dict[str, str]:
        return {
            "job_id": self.job_id,
            "task_id": self.task_id,
            "browser_session_id": self.browser_session_id,
            "auth_realm_id": self.auth_realm_id or "",
            "user_id": self.user_id,
            "agent_name": self.agent_name,
            "chat_session_id": self.chat_session_id,
            "action": self.action,
            "idempotency_key": self.idempotency_key or "",
            "reply_stream": self.reply_stream,
            "payload_json": json.dumps(self.payload, ensure_ascii=False),
            "created_at": self.created_at,
            "timeout_s": str(self.timeout_s),
        }

    @classmethod
    def from_stream_fields(cls, data: dict[str, Any]) -> "BrowserJob":
        data = _normalize_mapping(data)
        raw_payload = _to_text(data.get("payload_json", "{}")) or "{}"
        return cls(
            job_id=_to_text(data.get("job_id")),
            task_id=_to_text(data.get("task_id")),
            browser_session_id=_to_text(data.get("browser_session_id")),
            auth_realm_id=_optional_text(data.get("auth_realm_id")),
            user_id=_to_text(data.get("user_id")),
            agent_name=_to_text(data.get("agent_name")),
            chat_session_id=_to_text(data.get("chat_session_id")),
            action=_to_text(data.get("action")),
            payload=json.loads(raw_payload),
            idempotency_key=_optional_text(data.get("idempotency_key")),
            reply_stream=_to_text(data.get("reply_stream")),
            created_at=_to_text(data.get("created_at", utc_now_iso())),
            timeout_s=int(_to_text(data.get("timeout_s", "120")) or "120"),
        )


@dataclass(slots=True)
class BrowserEvent:
    event_id: str
    task_id: str
    job_id: str
    browser_session_id: str
    worker_id: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    auth_realm_id: str | None = None
    status: str = ""
    created_at: str = field(default_factory=utc_now_iso)

    def to_stream_fields(self) -> dict[str, str]:
        return {
            "event_id": self.event_id,
            "task_id": self.task_id,
            "job_id": self.job_id,
            "browser_session_id": self.browser_session_id,
            "auth_realm_id": self.auth_realm_id or "",
            "worker_id": self.worker_id,
            "event_type": self.event_type,
            "status": self.status,
            "payload_json": json.dumps(self.payload, ensure_ascii=False),
            "created_at": self.created_at,
        }

    @classmethod
    def from_stream_fields(cls, data: dict[str, Any]) -> "BrowserEvent":
        data = _normalize_mapping(data)
        raw_payload = _to_text(data.get("payload_json", "{}")) or "{}"
        return cls(
            event_id=_to_text(data.get("event_id")),
            task_id=_to_text(data.get("task_id")),
            job_id=_to_text(data.get("job_id")),
            browser_session_id=_to_text(data.get("browser_session_id")),
            auth_realm_id=_optional_text(data.get("auth_realm_id")),
            worker_id=_to_text(data.get("worker_id")),
            event_type=_to_text(data.get("event_type")),
            status=_to_text(data.get("status", "")),
            payload=json.loads(raw_payload),
            created_at=_to_text(data.get("created_at", utc_now_iso())),
        )


def _to_text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return "" if value is None else str(value)


def _optional_text(value: Any) -> str | None:
    text = _to_text(value).strip()
    return text or None


def _normalize_mapping(data: dict[Any, Any]) -> dict[str, Any]:
    return {_to_text(key): value for key, value in data.items()}
