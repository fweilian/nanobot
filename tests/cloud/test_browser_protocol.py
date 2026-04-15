from __future__ import annotations

from nanobot.cloud.browser_protocol import (
    AuthRealmMeta,
    BrowserEvent,
    BrowserJob,
    BrowserSessionMeta,
    auth_realm_id,
    browser_session_id,
    derive_realm_key,
)


def test_browser_ids_and_realm_key_helpers():
    assert browser_session_id("u1", "default", "s1") == "cloud:u1:default:s1:browser"
    assert browser_session_id("u1", "default", "s1", "tab-2") == "cloud:u1:default:s1:browser:tab-2"
    assert auth_realm_id("u1", "Google-Workspace") == "u1:google-workspace"
    assert derive_realm_key(configured_realm="Corp-SSO") == "corp-sso"
    assert derive_realm_key(issuer="https://accounts.example.com/oauth2") == "accounts.example.com"
    assert derive_realm_key(url="https://docs.example.com/path") == "docs.example.com"


def test_browser_job_round_trip():
    job = BrowserJob(
        job_id="job_1",
        task_id="task_1",
        browser_session_id="cloud:u1:default:s1:browser",
        auth_realm_id="u1:corp-sso",
        user_id="u1",
        agent_name="default",
        chat_session_id="s1",
        action="open_url",
        payload={"url": "https://example.com", "step": 1},
        reply_stream="nb:browser:events",
        timeout_s=90,
    )

    restored = BrowserJob.from_stream_fields(job.to_stream_fields())

    assert restored == job


def test_browser_job_from_stream_fields_accepts_byte_keys():
    raw = {
        b"job_id": b"job_1",
        b"task_id": b"task_1",
        b"browser_session_id": b"cloud:u1:default:s1:browser",
        b"auth_realm_id": b"u1:corp-sso",
        b"user_id": b"u1",
        b"agent_name": b"default",
        b"chat_session_id": b"s1",
        b"action": b"open_url",
        b"idempotency_key": b"abc",
        b"reply_stream": b"nb:browser:events",
        b"payload_json": b'{"url":"https://example.com"}',
        b"created_at": b"2026-04-15T10:00:00+00:00",
        b"timeout_s": b"120",
    }

    restored = BrowserJob.from_stream_fields(raw)

    assert restored.job_id == "job_1"
    assert restored.task_id == "task_1"
    assert restored.browser_session_id == "cloud:u1:default:s1:browser"
    assert restored.action == "open_url"
    assert restored.payload["url"] == "https://example.com"


def test_browser_event_round_trip():
    event = BrowserEvent(
        event_id="evt_1",
        task_id="task_1",
        job_id="job_1",
        browser_session_id="cloud:u1:default:s1:browser",
        auth_realm_id="u1:corp-sso",
        worker_id="worker-a",
        event_type="auth_realm_reused",
        status="started",
        payload={"reused": True},
    )

    restored = BrowserEvent.from_stream_fields(event.to_stream_fields())

    assert restored == event


def test_auth_realm_meta_mapping_and_domain_match():
    meta = AuthRealmMeta(
        user_id="u1",
        auth_realm_id="u1:corp-sso",
        realm_key="corp-sso",
        issuer="https://accounts.example.com",
        domain_patterns=["*.example.com", ".internal.example.com"],
    )

    restored = AuthRealmMeta.from_mapping(meta.to_mapping())

    assert restored == meta
    assert restored.matches_url("https://docs.example.com")
    assert restored.matches_url("https://a.internal.example.com")
    assert not restored.matches_url("https://other.org")


def test_browser_session_meta_mapping_round_trip():
    meta = BrowserSessionMeta(
        browser_session_id="cloud:u1:default:s1:browser",
        user_id="u1",
        agent_name="default",
        chat_session_id="s1",
        auth_realm_id="u1:corp-sso",
        current_url="https://example.com",
    )

    restored = BrowserSessionMeta.from_mapping(meta.to_mapping())

    assert restored == meta
