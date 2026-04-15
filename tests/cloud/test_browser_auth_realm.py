from __future__ import annotations

import pytest

from nanobot.cloud.browser_orchestrator import BrowserOrchestrator
from nanobot.cloud.browser_store import InMemoryBrowserStore


@pytest.mark.asyncio
async def test_orchestrator_reuses_auth_realm_across_chat_sessions():
    store = InMemoryBrowserStore()
    orchestrator = BrowserOrchestrator(store, event_stream=store.keys.event_stream)

    remembered = await orchestrator.remember_auth_success(
        user_id="alice",
        issuer="https://accounts.example.com",
        url="https://docs.example.com",
        auth_state=b"oauth-state",
        domain_patterns=["docs.example.com", "calendar.example.com"],
    )

    session_a = await orchestrator.plan_session(
        user_id="alice",
        agent_name="default",
        chat_session_id="session-a",
        url="https://docs.example.com",
    )
    session_b = await orchestrator.plan_session(
        user_id="alice",
        agent_name="default",
        chat_session_id="session-b",
        url="https://calendar.example.com",
    )

    assert session_a.browser_session_id != session_b.browser_session_id
    assert session_a.auth_realm_id == remembered.auth_realm_id
    assert session_b.auth_realm_id == remembered.auth_realm_id
    assert session_a.reused_auth is True
    assert session_b.reused_auth is True
    assert session_b.auth_state == b"oauth-state"


@pytest.mark.asyncio
async def test_orchestrator_submit_task_persists_realm_binding_and_queue_entry():
    store = InMemoryBrowserStore()
    orchestrator = BrowserOrchestrator(store, event_stream=store.keys.event_stream)
    await orchestrator.remember_auth_success(
        user_id="alice",
        configured_realm="corp-sso",
        url="https://portal.example.com",
        auth_state=b"secret",
        domain_patterns=["portal.example.com"],
    )

    job = await orchestrator.submit_task(
        user_id="alice",
        agent_name="default",
        chat_session_id="session-b",
        action="open_url",
        payload={"url": "https://portal.example.com/home"},
        configured_realm="corp-sso",
    )

    assert job.auth_realm_id == "alice:corp-sso"
    assert store.jobs
    task = await store.get_task(job.task_id)
    assert task is not None
    assert task["browser_session_id"] == "cloud:alice:default:session-b:browser"
    assert task["auth_realm_id"] == "alice:corp-sso"
    assert task["reused_auth"] == "1"

    session_meta = await store.get_session_meta("cloud:alice:default:session-b:browser")
    assert session_meta is not None
    assert session_meta.auth_realm_id == "alice:corp-sso"


@pytest.mark.asyncio
async def test_orchestrator_requires_new_login_when_realm_mismatches():
    store = InMemoryBrowserStore()
    orchestrator = BrowserOrchestrator(store, event_stream=store.keys.event_stream)
    await orchestrator.remember_auth_success(
        user_id="alice",
        configured_realm="corp-sso",
        url="https://portal.example.com",
        auth_state=b"secret",
        domain_patterns=["portal.example.com"],
    )

    plan = await orchestrator.plan_session(
        user_id="alice",
        agent_name="default",
        chat_session_id="session-c",
        url="https://other.example.net",
    )

    assert plan.reused_auth is False
    assert plan.auth_realm_id is None
