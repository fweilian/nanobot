"""Browser worker main loop and task execution."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.cloud.browser_protocol import (
    BrowserEvent,
    BrowserEventType,
    BrowserJob,
    BrowserSessionMeta,
)
from nanobot.cloud.browser_store import BrowserStore, RedisBrowserStore


class BrowserExecutor:
    """Executes browser jobs. Uses Playwright when available."""

    def __init__(self, *, shm_root: Path):
        self._shm_root = shm_root
        self._runtimes: dict[str, dict[str, Any]] = {}

    async def execute(self, job: BrowserJob, auth_state: bytes | None) -> dict[str, Any]:
        action = job.action
        if action == "close_session":
            self._runtimes.pop(job.browser_session_id, None)
            return {"status": "completed", "message": "browser session closed"}
        if action == "extract":
            return {"status": "completed", "message": "page extraction queued", "mode": job.payload.get("mode", "summary")}
        if action == "navigate":
            return {"status": "completed", "message": job.payload.get("instruction", "")}

        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            return {"status": "failed", "message": f"Playwright unavailable: {type(exc).__name__}"}

        runtime = self._runtimes.get(job.browser_session_id)
        if runtime is None:
            playwright = await async_playwright().start()
            browser = await playwright.chromium.launch(headless=True)
            storage_state = None
            if auth_state:
                storage_state = json.loads(auth_state.decode("utf-8"))
            context = await browser.new_context(storage_state=storage_state)
            page = await context.new_page()
            runtime = {
                "playwright": playwright,
                "browser": browser,
                "context": context,
                "page": page,
            }
            self._runtimes[job.browser_session_id] = runtime

        page = runtime["page"]
        url = job.payload.get("url")
        if url:
            await page.goto(url, wait_until="domcontentloaded")

        if action == "begin_login":
            buffer = await page.screenshot(full_page=False, type="png")
            return {
                "status": "awaiting_user",
                "media_bytes": buffer,
                "content_type": "image/png",
                "filename": "qr.png",
                "message": "Scan the QR code to continue login.",
                "current_url": page.url,
            }

        if action == "open_url":
            auth_state_bytes = json.dumps(await runtime["context"].storage_state(), ensure_ascii=False).encode("utf-8")
            return {
                "status": "completed",
                "message": "page opened",
                "current_url": page.url,
                "title": await page.title(),
                "auth_state_bytes": auth_state_bytes,
            }

        auth_state_bytes = json.dumps(await runtime["context"].storage_state(), ensure_ascii=False).encode("utf-8")
        return {
            "status": "completed",
            "message": f"action {action} completed",
            "current_url": page.url,
            "auth_state_bytes": auth_state_bytes,
        }


@dataclass(slots=True)
class BrowserWorker:
    store: BrowserStore
    worker_id: str
    auth_ttl_s: int
    qr_ttl_s: int
    executor: BrowserExecutor

    async def process_job(self, job: BrowserJob) -> None:
        logger.info(
            "browser worker {} processing task_id={} action={} browser_session={} auth_realm={}",
            self.worker_id,
            job.task_id,
            job.action,
            job.browser_session_id,
            job.auth_realm_id or "",
        )
        await self.store.save_task(
            job.task_id,
            {
                "status": "running",
                "action": job.action,
                "browser_session_id": job.browser_session_id,
                "auth_realm_id": job.auth_realm_id or "",
                "current_worker_id": self.worker_id,
            },
            ttl_s=max(job.timeout_s, 60),
        )
        auth_state = await self.store.load_auth_state(job.auth_realm_id) if job.auth_realm_id else None
        result = await self.executor.execute(job, auth_state)

        media_id = None
        auth_state_bytes = result.pop("auth_state_bytes", None)
        if media_bytes := result.pop("media_bytes", None):
            media_id = f"media_{uuid.uuid4().hex[:12]}"
            await self.store.save_media(
                media_id,
                data=media_bytes,
                content_type=str(result.pop("content_type", "image/png")),
                filename=str(result.pop("filename", "image.png")),
                owner_user_id=job.user_id,
                browser_session_id=job.browser_session_id,
                ttl_s=self.qr_ttl_s,
            )

        status = str(result.get("status", "completed"))
        task_result = dict(result)
        if media_id:
            task_result["media_id"] = media_id
        if auth_state_bytes is not None and job.auth_realm_id and status == "completed":
            await self.store.save_auth_state(job.auth_realm_id, auth_state_bytes, ttl_s=self.auth_ttl_s)
        await self.store.save_task(
            job.task_id,
            {
                "status": status,
                "action": job.action,
                "browser_session_id": job.browser_session_id,
                "auth_realm_id": job.auth_realm_id or "",
                "current_worker_id": self.worker_id,
                "result_json": json.dumps(task_result, ensure_ascii=False),
            },
            ttl_s=max(job.timeout_s, 60),
        )
        meta = await self.store.get_session_meta(job.browser_session_id)
        if meta is None:
            meta = BrowserSessionMeta(
                browser_session_id=job.browser_session_id,
                user_id=job.user_id,
                agent_name=job.agent_name,
                chat_session_id=job.chat_session_id,
                auth_realm_id=job.auth_realm_id,
            )
        meta.status = "authenticated" if status == "completed" else status
        meta.current_url = str(task_result.get("current_url") or meta.current_url or "")
        meta.last_task_id = job.task_id
        meta.auth_realm_id = job.auth_realm_id
        await self.store.save_session_meta(meta, ttl_s=self.auth_ttl_s)
        await self.store.append_event(
            BrowserEvent(
                event_id=f"evt_{uuid.uuid4().hex[:12]}",
                task_id=job.task_id,
                job_id=job.job_id,
                browser_session_id=job.browser_session_id,
                auth_realm_id=job.auth_realm_id,
                worker_id=self.worker_id,
                event_type=(
                    BrowserEventType.QR_READY if status == "awaiting_user"
                    else BrowserEventType.COMPLETED if status == "completed"
                    else BrowserEventType.FAILED
                ),
                status=status,
                payload=task_result,
            )
        )
        logger.info(
            "browser worker {} finished task_id={} status={}",
            self.worker_id,
            job.task_id,
            status,
        )


class RedisBrowserJobConsumer:
    """Consumes browser jobs from Redis streams."""

    def __init__(self, client, store: RedisBrowserStore, worker: BrowserWorker, *, block_ms: int = 1000):
        self._client = client
        self._store = store
        self._worker = worker
        self._block_ms = block_ms

    async def ensure_group(self) -> None:
        try:
            await self._client.xgroup_create(
                self._store.keys.job_stream,
                "workers",
                id="0",
                mkstream=True,
            )
        except Exception:
            pass

    async def run_forever(self) -> None:
        await self.ensure_group()
        while True:
            streams = await self._client.xreadgroup(
                "workers",
                self._worker.worker_id,
                {self._store.keys.job_stream: ">"},
                count=1,
                block=self._block_ms,
            )
            if not streams:
                continue
            for _stream_name, entries in streams:
                for stream_id, data in entries:
                    job = BrowserJob.from_stream_fields(data)
                    try:
                        await self._worker.process_job(job)
                    except Exception as exc:
                        logger.exception("browser worker failed processing {}: {}", job.job_id, exc)
                        await self._store.save_task(
                            job.task_id,
                            {
                                "status": "failed",
                                "action": job.action,
                                "browser_session_id": job.browser_session_id,
                                "auth_realm_id": job.auth_realm_id or "",
                                "error_message": str(exc),
                            },
                            ttl_s=max(job.timeout_s, 60),
                        )
                    finally:
                        await self._client.xack(self._store.keys.job_stream, "workers", stream_id)
