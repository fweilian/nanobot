from __future__ import annotations

import json

import pytest

from nanobot.browser_worker.runner import BrowserWorker
from nanobot.cloud.browser_protocol import BrowserJob
from nanobot.cloud.browser_store import InMemoryBrowserStore


class FakeExecutor:
    def __init__(self, result):
        self.result = result
        self.calls = []

    async def execute(self, job, auth_state):
        self.calls.append((job, auth_state))
        return dict(self.result)


@pytest.mark.asyncio
async def test_worker_process_job_stores_qr_media_and_updates_task():
    store = InMemoryBrowserStore()
    worker = BrowserWorker(
        store=store,
        worker_id="worker-a",
        auth_ttl_s=3600,
        qr_ttl_s=120,
        executor=FakeExecutor(
            {
                "status": "awaiting_user",
                "media_bytes": b"png-bytes",
                "content_type": "image/png",
                "filename": "qr.png",
                "message": "scan now",
                "current_url": "https://example.com/login",
            }
        ),
    )
    job = BrowserJob(
        job_id="job-1",
        task_id="task-1",
        browser_session_id="cloud:alice:default:s1:browser",
        auth_realm_id="alice:corp-sso",
        user_id="alice",
        agent_name="default",
        chat_session_id="s1",
        action="begin_login",
        payload={"url": "https://example.com/login"},
        reply_stream=store.keys.event_stream,
    )

    await worker.process_job(job)

    task = await store.get_task("task-1")
    assert task is not None
    assert task["status"] == "awaiting_user"
    result = json.loads(task["result_json"])
    assert result["message"] == "scan now"
    assert "media_id" in result

    media = await store.load_media(result["media_id"])
    assert media is not None
    assert media["bytes"] == b"png-bytes"
    assert media["owner_user_id"] == "alice"


@pytest.mark.asyncio
async def test_worker_process_job_marks_completed_and_updates_session_meta():
    store = InMemoryBrowserStore()
    worker = BrowserWorker(
        store=store,
        worker_id="worker-a",
        auth_ttl_s=3600,
        qr_ttl_s=120,
        executor=FakeExecutor(
            {
                "status": "completed",
                "message": "page opened",
                "current_url": "https://example.com/home",
            }
        ),
    )
    job = BrowserJob(
        job_id="job-2",
        task_id="task-2",
        browser_session_id="cloud:alice:default:s2:browser",
        auth_realm_id="alice:corp-sso",
        user_id="alice",
        agent_name="default",
        chat_session_id="s2",
        action="open_url",
        payload={"url": "https://example.com/home"},
        reply_stream=store.keys.event_stream,
    )

    await worker.process_job(job)

    task = await store.get_task("task-2")
    assert task is not None
    assert task["status"] == "completed"

    meta = await store.get_session_meta("cloud:alice:default:s2:browser")
    assert meta is not None
    assert meta.current_url == "https://example.com/home"
    assert meta.auth_realm_id == "alice:corp-sso"


@pytest.mark.asyncio
async def test_worker_persists_auth_state_on_completed_job():
    store = InMemoryBrowserStore()
    worker = BrowserWorker(
        store=store,
        worker_id="worker-a",
        auth_ttl_s=3600,
        qr_ttl_s=120,
        executor=FakeExecutor(
            {
                "status": "completed",
                "message": "logged in",
                "current_url": "https://example.com/home",
                "auth_state_bytes": b'{"cookies":[],"origins":[]}',
            }
        ),
    )
    job = BrowserJob(
        job_id="job-3",
        task_id="task-3",
        browser_session_id="cloud:alice:default:s3:browser",
        auth_realm_id="alice:corp-sso",
        user_id="alice",
        agent_name="default",
        chat_session_id="s3",
        action="navigate",
        payload={"instruction": "continue"},
        reply_stream=store.keys.event_stream,
    )

    await worker.process_job(job)

    assert await store.load_auth_state("alice:corp-sso") == b'{"cookies":[],"origins":[]}'
