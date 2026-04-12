from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.cloud.auth import AuthenticatedUser
from nanobot.cloud.config import AuthSettings, CloudServiceSettings, ManagedProviderView, S3Settings
from nanobot.cloud.runtime import CloudChatResult, CloudRuntimeService, CloudWorkspaceManager
from nanobot.cloud.server import create_app
from tests.cloud.support import MemoryStore


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
            "s3": S3Settings(bucket="test-bucket"),
        }
    )


@pytest.fixture
def app(settings: CloudServiceSettings):
    store = MemoryStore()
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
        on_stream=None,
        on_stream_end=None,
    ):
        sessions = runtime_dir / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        (sessions / f"{session_key.replace(':', '_')}.jsonl").write_text(content, encoding="utf-8")
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


@pytest.fixture
def client(app):
    fastapi_testclient = pytest.importorskip("fastapi.testclient")
    return fastapi_testclient.TestClient(app)
