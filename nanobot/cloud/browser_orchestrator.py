"""Agent-side browser control-plane orchestrator."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from nanobot.cloud.browser_protocol import (
    AuthRealmMeta,
    BrowserJob,
    BrowserSessionMeta,
    auth_realm_id,
    browser_session_id,
    derive_realm_key,
    utc_now_iso,
)
from nanobot.cloud.browser_store import BrowserStore, find_reusable_auth_realm

_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "expired"})


@dataclass(slots=True)
class BrowserSessionPlan:
    browser_session_id: str
    auth_realm_id: str | None
    reused_auth: bool
    auth_state: bytes | None
    realm: AuthRealmMeta | None


class BrowserOrchestrator:
    """High-level browser-session planning and task submission."""

    def __init__(
        self,
        store: BrowserStore,
        *,
        event_stream: str,
        auth_ttl_s: int = 3600,
        task_ttl_s: int = 900,
    ) -> None:
        self._store = store
        self._event_stream = event_stream
        self._auth_ttl_s = auth_ttl_s
        self._task_ttl_s = task_ttl_s

    async def plan_session(
        self,
        *,
        user_id: str,
        agent_name: str,
        chat_session_id: str,
        url: str | None = None,
        issuer: str | None = None,
        configured_realm: str | None = None,
    ) -> BrowserSessionPlan:
        realm = await find_reusable_auth_realm(
            self._store,
            user_id=user_id,
            url=url,
            issuer=issuer,
            configured_realm=configured_realm,
        )
        auth_state = await self._store.load_auth_state(realm.auth_realm_id) if realm else None
        session_id = browser_session_id(user_id, agent_name, chat_session_id)
        meta = await self._store.get_session_meta(session_id)
        if meta is None:
            meta = BrowserSessionMeta(
                browser_session_id=session_id,
                user_id=user_id,
                agent_name=agent_name,
                chat_session_id=chat_session_id,
                auth_realm_id=realm.auth_realm_id if realm else None,
            )
        elif realm and not meta.auth_realm_id:
            meta.auth_realm_id = realm.auth_realm_id
        meta.updated_at = utc_now_iso()
        await self._store.save_session_meta(meta, ttl_s=self._task_ttl_s)
        return BrowserSessionPlan(
            browser_session_id=session_id,
            auth_realm_id=realm.auth_realm_id if realm else None,
            reused_auth=auth_state is not None,
            auth_state=auth_state,
            realm=realm,
        )

    async def remember_auth_success(
        self,
        *,
        user_id: str,
        url: str | None = None,
        issuer: str | None = None,
        configured_realm: str | None = None,
        auth_state: bytes,
        domain_patterns: list[str] | None = None,
        expires_at: str | None = None,
    ) -> AuthRealmMeta:
        realm_key = derive_realm_key(url=url, issuer=issuer, configured_realm=configured_realm)
        if not realm_key:
            raise ValueError("Could not derive auth realm key")
        realm_id = auth_realm_id(user_id, realm_key)
        existing = await self._store.get_auth_realm(realm_id)
        meta = existing or AuthRealmMeta(
            user_id=user_id,
            auth_realm_id=realm_id,
            realm_key=realm_key,
            issuer=issuer,
            domain_patterns=domain_patterns or (
                [host] if (host := derive_realm_key(url=url)) is not None else []
            ),
        )
        if issuer:
            meta.issuer = issuer
        if domain_patterns:
            meta.domain_patterns = sorted(set(domain_patterns))
        meta.expires_at = expires_at
        meta.last_validated_at = utc_now_iso()
        meta.last_used_at = meta.last_validated_at
        meta.auth_version += 0 if existing is None else 1
        await self._store.save_auth_realm(meta, ttl_s=self._auth_ttl_s)
        await self._store.save_auth_state(meta.auth_realm_id, auth_state, ttl_s=self._auth_ttl_s)
        return meta

    async def submit_task(
        self,
        *,
        user_id: str,
        agent_name: str,
        chat_session_id: str,
        action: str,
        payload: dict[str, Any] | None = None,
        issuer: str | None = None,
        configured_realm: str | None = None,
        timeout_s: int = 120,
    ) -> BrowserJob:
        payload = dict(payload or {})
        plan = await self.plan_session(
            user_id=user_id,
            agent_name=agent_name,
            chat_session_id=chat_session_id,
            url=payload.get("url"),
            issuer=issuer,
            configured_realm=configured_realm,
        )
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        job = BrowserJob(
            job_id=f"job_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            browser_session_id=plan.browser_session_id,
            auth_realm_id=plan.auth_realm_id,
            user_id=user_id,
            agent_name=agent_name,
            chat_session_id=chat_session_id,
            action=action,
            payload=payload,
            reply_stream=self._event_stream,
            timeout_s=timeout_s,
            idempotency_key=self._idempotency_key(
                user_id=user_id,
                agent_name=agent_name,
                chat_session_id=chat_session_id,
                action=action,
                payload=payload,
                auth_realm_id=plan.auth_realm_id,
            ),
        )
        await self._store.save_task(
            task_id,
            {
                "status": "queued",
                "action": action,
                "browser_session_id": plan.browser_session_id,
                "auth_realm_id": plan.auth_realm_id or "",
                "reused_auth": "1" if plan.reused_auth else "0",
                "created_at": utc_now_iso(),
            },
            ttl_s=self._task_ttl_s,
        )
        await self._store.append_job(job)
        return job

    async def wait_for_terminal_status(
        self,
        task_id: str,
        *,
        timeout_s: float = 30.0,
        poll_interval_s: float = 0.2,
    ) -> dict[str, str]:
        deadline = asyncio.get_running_loop().time() + timeout_s
        while True:
            task = await self._store.get_task(task_id)
            if task is not None and task.get("status") in _TERMINAL_STATUSES:
                return task
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(f"Timed out waiting for task {task_id}")
            await asyncio.sleep(poll_interval_s)

    async def wait_for_status_change(
        self,
        task_id: str,
        *,
        timeout_s: float = 30.0,
        poll_interval_s: float = 0.2,
        target_statuses: tuple[str, ...] = ("completed",),
    ) -> dict[str, str]:
        deadline = asyncio.get_running_loop().time() + timeout_s
        while True:
            task = await self._store.get_task(task_id)
            if task is not None and task.get("status") in target_statuses:
                return task
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(f"Timed out waiting for task {task_id}")
            await asyncio.sleep(poll_interval_s)

    @staticmethod
    def _idempotency_key(
        *,
        user_id: str,
        agent_name: str,
        chat_session_id: str,
        action: str,
        payload: dict[str, Any],
        auth_realm_id: str | None,
    ) -> str:
        digest = hashlib.sha256()
        digest.update(user_id.encode("utf-8"))
        digest.update(agent_name.encode("utf-8"))
        digest.update(chat_session_id.encode("utf-8"))
        digest.update(action.encode("utf-8"))
        digest.update((auth_realm_id or "").encode("utf-8"))
        digest.update(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))
        return digest.hexdigest()
