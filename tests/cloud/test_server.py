from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from nanobot.cloud.auth import AuthenticatedUser
from nanobot.cloud.browser_orchestrator import BrowserOrchestrator
from nanobot.cloud.browser_store import InMemoryBrowserStore
from nanobot.cloud.config import (
    AuthSettings,
    CloudAgentConfig,
    CloudServiceSettings,
    ManagedProviderView,
    RedisSettings,
    S3Settings,
)
from nanobot.cloud.runtime import CloudChatResult, CloudRuntimeService, CloudWorkspaceManager
from nanobot.cloud.server import create_app
from nanobot.cloud.skills_cache import SkillStageBudgetExceededError
from nanobot.session.manager import SessionManager
from tests.cloud.support import InMemoryLockManager, InMemorySessionStore, MemoryStore


class StubVerifier:
    def verify(self, token: str) -> AuthenticatedUser:
        return AuthenticatedUser(user_id="alice", claims={"sub": "alice"}, token=token)


@pytest.fixture
def settings(tmp_path: Path):
    config_path = tmp_path / "platform.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": {"openrouter": {"apiKey": "sk-test"}},
                "agents": {"defaults": {"model": "openai/gpt-4.1"}},
            }
        ),
        encoding="utf-8",
    )
    return CloudServiceSettings.model_validate(
        {
            "nanobot_config_path": config_path,
            "local_cache_dir": tmp_path / "cache",
            "auth": AuthSettings(shared_secret="this-is-a-long-test-secret-for-hs256", algorithms=["HS256"]),
            "redis": RedisSettings(url="redis://unused/0", key_prefix="test-cloud", session_ttl_s=300, lock_ttl_s=30),
            "s3": S3Settings(bucket="test-bucket"),
        }
    )


@pytest.fixture
def app(settings: CloudServiceSettings):
    store = MemoryStore()
    session_store = InMemorySessionStore()
    lock_manager = InMemoryLockManager()
    browser_store = InMemoryBrowserStore(key_prefix="test-cloud:browser")
    browser_orchestrator = BrowserOrchestrator(
        browser_store,
        event_stream=browser_store.keys.event_stream,
        auth_ttl_s=settings.browser.auth_ttl_s,
        task_ttl_s=settings.browser.task_ttl_s,
    )
    workspace_manager = CloudWorkspaceManager(
        store=store,
        cache_root=settings.cache_root,
        workspace_prefix=settings.workspace_prefix,
        platform_provider=ManagedProviderView(provider="openrouter", model="openai/gpt-4.1"),
    )

    async def executor(
        root,
        runtime_dir,
        builtin_dir,
        selected_skills_dir,
        *,
        user,
        agent,
        session_key,
        content,
        message_id=None,
        on_stream=None,
        on_stream_end=None,
        on_tool_event=None,
    ):
        manager = SessionManager(runtime_dir)
        session = manager.get_or_create(session_key)
        session.add_message("user", content)
        session.add_message("assistant", f"reply:{content}")
        manager.save(session)
        if on_tool_event:
            await on_tool_event(
                {
                    "event": "tool_call_started",
                    "tool_call_id": "tool-1",
                    "tool_name": "read_file",
                    "args_text": "{\"path\":\"README.md\"}",
                }
            )
            await on_tool_event(
                {
                    "event": "tool_call_completed",
                    "tool_call_id": "tool-1",
                    "tool_name": "read_file",
                    "args_text": "{\"path\":\"README.md\"}",
                    "result_text": "README body",
                }
            )
        if on_stream:
            await on_stream("hello ")
            await on_stream("world")
        if on_stream_end:
            await on_stream_end(resuming=False)
        return CloudChatResult(content=f"reply:{content}", model="openai/gpt-4.1")

    runtime_service = CloudRuntimeService(
        settings=settings,
        workspace_manager=workspace_manager,
        platform_config_path=settings.nanobot_config_path,
        session_store=session_store,
        lock_manager=lock_manager,
        browser_store=browser_store,
        browser_orchestrator=browser_orchestrator,
        executor=executor,
    )
    return create_app(runtime_service=runtime_service, token_verifier=StubVerifier(), settings=settings)


def test_health_and_models(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}

    models = client.get("/v1/models")
    assert models.status_code == 200
    assert models.json()["data"][0]["id"] == "openai/gpt-4.1"


def test_media_endpoint_requires_owner_and_returns_bytes(client):
    runtime_service = client.app.state.runtime_service
    store = runtime_service.browser_store
    assert store is not None

    import asyncio

    asyncio.run(
        store.save_media(
            "media-test",
            data=b"png-bytes",
            content_type="image/png",
            filename="qr.png",
            owner_user_id="alice",
            browser_session_id="cloud:alice:default:s1:browser",
            ttl_s=60,
        )
    )

    resp = client.get("/v1/media/media-test", headers={"Authorization": "Bearer token"})
    assert resp.status_code == 200
    assert resp.content == b"png-bytes"
    assert resp.headers["content-type"].startswith("image/png")


def test_agents_bootstrap_and_chat(client):
    agents = client.get("/v1/agents", headers={"Authorization": "Bearer token"})
    assert agents.status_code == 200
    assert agents.json()["data"][0]["id"] == "default"

    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer token"},
        json={
            "agent": "default",
            "session_id": "thread-1",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["choices"][0]["message"]["content"] == "reply:hello"
    assert body["message"]["role"] == "assistant"
    assert any(block["type"] == "markdown" for block in body["message"]["blocks"])
    assert any(block["type"] == "tool_call" for block in body["message"]["blocks"])


def test_session_crud_round_trip(client):
    created = client.post(
        "/v1/agents/default/sessions",
        headers={"Authorization": "Bearer token"},
    )
    assert created.status_code == 200
    payload = created.json()
    session_id = payload["id"]
    assert payload["agentId"] == "default"
    assert payload["title"] == "新对话"

    listed = client.get(
        "/v1/agents/default/sessions",
        headers={"Authorization": "Bearer token"},
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == [session_id]

    detail = client.get(
        f"/v1/agents/default/sessions/{session_id}",
        headers={"Authorization": "Bearer token"},
    )
    assert detail.status_code == 200
    assert detail.json()["messages"] == []

    renamed = client.patch(
        f"/v1/agents/default/sessions/{session_id}",
        headers={"Authorization": "Bearer token"},
        json={"title": "Renamed session"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "Renamed session"

    detail = client.get(
        f"/v1/agents/default/sessions/{session_id}",
        headers={"Authorization": "Bearer token"},
    )
    assert detail.status_code == 200
    assert detail.json()["title"] == "Renamed session"

    deleted = client.delete(
        f"/v1/agents/default/sessions/{session_id}",
        headers={"Authorization": "Bearer token"},
    )
    assert deleted.status_code == 204
    assert deleted.content == b""

    listed = client.get(
        "/v1/agents/default/sessions",
        headers={"Authorization": "Bearer token"},
    )
    assert listed.status_code == 200
    assert listed.json()["data"] == []

    missing = client.get(
        f"/v1/agents/default/sessions/{session_id}",
        headers={"Authorization": "Bearer token"},
    )
    assert missing.status_code == 404


def test_agents_listing_uses_remote_metadata_without_workspace_checkout(client, monkeypatch):
    runtime_service = client.app.state.runtime_service
    manager = runtime_service.workspace_manager
    root = manager.ensure_user_workspace("alice")
    try:
        cfg = manager.load_workspace_config(root)
        cfg.agents["research"] = "agents/research/config.json"
        manager.save_workspace_config(root, cfg)
        manager.save_agent_config(root, CloudAgentConfig(name="research", description="Research agent"))
        manager.upload_user_workspace("alice", root)
    finally:
        manager.cleanup_workspace(root)

    def fail(user_id: str):
        raise AssertionError(f"workspace checkout should not be used for listing: {user_id}")

    monkeypatch.setattr(manager, "ensure_user_workspace", fail)

    resp = client.get("/v1/agents", headers={"Authorization": "Bearer token"})

    assert resp.status_code == 200
    assert [agent["id"] for agent in resp.json()["data"]] == ["default", "research"]


def test_session_listing_uses_manifest_without_workspace_checkout(client, monkeypatch):
    created = client.post(
        "/v1/agents/default/sessions",
        headers={"Authorization": "Bearer token"},
    )
    assert created.status_code == 200
    session_id = created.json()["id"]

    runtime_service = client.app.state.runtime_service
    manager = runtime_service.workspace_manager

    def fail(user_id: str):
        raise AssertionError(f"workspace checkout should not be used for session listing: {user_id}")

    monkeypatch.setattr(manager, "ensure_user_workspace", fail)

    listed = client.get(
        "/v1/agents/default/sessions",
        headers={"Authorization": "Bearer token"},
    )

    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == [session_id]


def test_agents_listing_for_new_user_returns_default_before_bootstrap_finishes(client, monkeypatch):
    runtime_service = client.app.state.runtime_service
    manager = runtime_service.workspace_manager
    config_key = manager.workspace_config_key("alice")

    def fail(user_id: str):
        raise AssertionError(f"workspace checkout should not be used for listing: {user_id}")

    monkeypatch.setattr(manager, "ensure_user_workspace", fail)

    resp = client.get("/v1/agents", headers={"Authorization": "Bearer token"})

    assert resp.status_code == 200
    assert resp.json()["data"][0]["id"] == "default"
    for _ in range(100):
        if manager.store.exists(config_key):
            break
        time.sleep(0.01)
    assert manager.store.exists(config_key)


def test_session_detail_returns_history_after_chat(client):
    created = client.post(
        "/v1/agents/default/sessions",
        headers={"Authorization": "Bearer token"},
    )
    session_id = created.json()["id"]

    chat = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer token"},
        json={
            "agent": "default",
            "session_id": session_id,
            "messages": [{"role": "user", "content": "hello from history"}],
        },
    )
    assert chat.status_code == 200

    detail = client.get(
        f"/v1/agents/default/sessions/{session_id}",
        headers={"Authorization": "Bearer token"},
    )
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["title"].startswith("hello from history")
    assert [message["role"] for message in payload["messages"]] == ["user", "assistant"]
    assert payload["messages"][0]["blocks"][0]["content"] == "hello from history"
    assert payload["messages"][1]["blocks"][0]["type"] == "markdown"


def test_streaming_chat_returns_sse(client):
    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer token"},
        json={
            "agent": "default",
            "session_id": "thread-1",
            "stream": True,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert "data: [DONE]" in resp.text


def test_streaming_first_send_failure_cleans_up_empty_session(client, monkeypatch):
    created = client.post(
        "/v1/agents/default/sessions",
        headers={"Authorization": "Bearer token"},
    )
    session_id = created.json()["id"]
    runtime_service = client.app.state.runtime_service

    async def fail(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(runtime_service, "_executor", fail)

    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer token"},
        json={
            "agent": "default",
            "session_id": session_id,
            "cleanup_empty_session_on_error": True,
            "stream": True,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    assert resp.status_code == 200
    assert "server_error" in resp.text

    listed = client.get(
        "/v1/agents/default/sessions",
        headers={"Authorization": "Bearer token"},
    )
    assert listed.status_code == 200
    assert listed.json()["data"] == []


def test_streaming_failure_keeps_session_if_user_turn_is_already_durable(client, monkeypatch):
    created = client.post(
        "/v1/agents/default/sessions",
        headers={"Authorization": "Bearer token"},
    )
    session_id = created.json()["id"]
    runtime_service = client.app.state.runtime_service
    manager = runtime_service.workspace_manager
    root = manager.ensure_user_workspace("alice")
    try:
        session_manager = SessionManager(root)
        session = session_manager.get_or_create(f"cloud:alice:default:{session_id}")
        session.add_message("user", "already durable")
        session.metadata["title"] = "already durable"
        session_manager.save(session)
        manager.upload_user_workspace("alice", root)
    finally:
        manager.cleanup_workspace(root)

    async def fail(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(runtime_service, "_executor", fail)

    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer token"},
        json={
            "agent": "default",
            "session_id": session_id,
            "cleanup_empty_session_on_error": True,
            "stream": True,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    assert resp.status_code == 200
    assert "server_error" in resp.text

    listed = client.get(
        "/v1/agents/default/sessions",
        headers={"Authorization": "Bearer token"},
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()["data"]] == [session_id]


def test_streaming_chat_includes_tool_call_events(client):
    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer token"},
        json={
          "agent": "default",
          "session_id": "thread-1",
          "stream": True,
          "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert resp.status_code == 200
    assert "tool_call_started" in resp.text
    assert "tool_call_completed" in resp.text
    assert "\"tool_name\": \"read_file\"" in resp.text


def test_non_stream_response_preserves_interleaved_text_and_tool_order(client, monkeypatch):
    runtime_service = client.app.state.runtime_service

    async def fake_run_chat(*args, **kwargs):
        on_stream = kwargs.get("on_stream")
        on_tool_event = kwargs.get("on_tool_event")
        if on_stream:
            await on_stream("before tool")
        if on_tool_event:
            await on_tool_event(
                {
                    "event": "tool_call_started",
                    "tool_call_id": "tool-1",
                    "tool_name": "read_file",
                    "args_text": "{\"path\":\"README.md\"}",
                }
            )
            await on_tool_event(
                {
                    "event": "tool_call_completed",
                    "tool_call_id": "tool-1",
                    "tool_name": "read_file",
                    "args_text": "{\"path\":\"README.md\"}",
                    "result_text": "README body",
                }
            )
        if on_stream:
            await on_stream(" after tool")
        return CloudChatResult(content="before tool after tool", model="openai/gpt-4.1")

    monkeypatch.setattr(runtime_service, "run_chat", fake_run_chat)

    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer token"},
        json={
            "agent": "default",
            "session_id": "thread-1",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert resp.status_code == 200
    blocks = resp.json()["message"]["blocks"]
    assert [block["type"] for block in blocks] == ["markdown", "tool_call", "markdown"]


def test_streaming_unknown_agent_returns_404(client):
    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer token"},
        json={
            "agent": "missing",
            "session_id": "thread-1",
            "stream": True,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )
    assert resp.status_code == 404


def test_streaming_missing_skill_returns_404_before_stream_starts(client, monkeypatch):
    runtime_service = client.app.state.runtime_service
    original = runtime_service.load_agent_metadata

    def fake_load_agent_metadata(user_id: str, agent_name: str):
        agent = original(user_id, agent_name)
        agent.skills = ["missing-skill"]
        return agent

    monkeypatch.setattr(runtime_service, "load_agent_metadata", fake_load_agent_metadata)

    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer token"},
        json={
            "agent": "default",
            "session_id": "thread-1",
            "stream": True,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert resp.status_code == 404


def test_conflicting_chat_request_returns_409(client):
    lock_manager = client.app.state.runtime_service.lock_manager
    scope = client.app.state.runtime_service._lock_scope("alice", "default", "thread-1")
    import asyncio

    asyncio.run(lock_manager.acquire(scope, 30))

    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer token"},
        json={
            "agent": "default",
            "session_id": "thread-1",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "session_locked"


def test_budget_exceeded_returns_507_for_non_stream(client, monkeypatch):
    async def fail(*args, **kwargs):
        raise SkillStageBudgetExceededError(
            requested_bytes=200,
            request_budget_bytes=100,
            instance_budget_bytes=1000,
            current_instance_bytes=0,
        )

    monkeypatch.setattr(client.app.state.runtime_service, "reserve_chat_execution", fail)

    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer token"},
        json={
            "agent": "default",
            "session_id": "thread-1",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert resp.status_code == 507
    assert resp.json()["error"]["code"] == "skill_stage_budget_exceeded"


def test_budget_exceeded_returns_507_for_stream(client, monkeypatch):
    async def fail(*args, **kwargs):
        raise SkillStageBudgetExceededError(
            requested_bytes=200,
            request_budget_bytes=100,
            instance_budget_bytes=1000,
            current_instance_bytes=0,
        )

    monkeypatch.setattr(client.app.state.runtime_service, "reserve_chat_execution", fail)

    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer token"},
        json={
            "agent": "default",
            "session_id": "thread-1",
            "stream": True,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert resp.status_code == 507
    assert resp.json()["error"]["code"] == "skill_stage_budget_exceeded"


def test_streaming_post_start_failure_returns_sse_error_event(client, monkeypatch):
    runtime_service = client.app.state.runtime_service

    async def fail(*args, **kwargs):
        raise FileNotFoundError("missing during stream")

    monkeypatch.setattr(runtime_service, "run_chat", fail)

    resp = client.post(
        "/v1/chat/completions",
        headers={"Authorization": "Bearer token"},
        json={
            "agent": "default",
            "session_id": "thread-1",
            "stream": True,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert resp.status_code == 200
    assert "not_found" in resp.text
    assert "missing during stream" in resp.text
    assert "data: [DONE]" in resp.text


@pytest.fixture
def client(app):
    fastapi_testclient = pytest.importorskip("fastapi.testclient")
    return fastapi_testclient.TestClient(app)
