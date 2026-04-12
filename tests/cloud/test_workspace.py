from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanobot.cloud.auth import AuthenticatedUser
from nanobot.cloud.config import ManagedProviderView
from nanobot.cloud.runtime import CloudChatResult, CloudRuntimeService, CloudWorkspaceManager
from nanobot.cloud.session_store import InMemorySessionStore, session_file_path
from tests.cloud.support import InMemoryLockManager, MemoryStore


def test_first_login_bootstraps_workspace(tmp_path: Path):
    manager = CloudWorkspaceManager(
        store=MemoryStore(),
        cache_root=tmp_path,
        workspace_prefix="workspaces",
        platform_provider=ManagedProviderView(provider="openrouter", model="openai/gpt-4.1"),
    )

    root = manager.ensure_user_workspace("alice")
    try:
        config = manager.load_workspace_config(root)
        agent = manager.load_agent_config(root, "default")
        assert config.user_id == "alice"
        assert config.default_agent == "default"
        assert "default" in config.agents
        assert agent.name == "default"
        assert (root / "memory" / "MEMORY.md").exists()
    finally:
        manager.cleanup_workspace(root)


def test_runtime_materialization_only_keeps_selected_skills(tmp_path: Path):
    manager = CloudWorkspaceManager(
        store=MemoryStore(),
        cache_root=tmp_path,
        workspace_prefix="workspaces",
        platform_provider=ManagedProviderView(provider="openrouter", model="openai/gpt-4.1"),
    )

    root = manager.ensure_user_workspace("alice")
    try:
        agent_dir = root / "agents" / "default" / "skills" / "local-skill"
        agent_dir.mkdir(parents=True)
        (agent_dir / "SKILL.md").write_text("# local skill", encoding="utf-8")
        agent = manager.load_agent_config(root, "default")
        agent.skills = ["local-skill"]
        manager.save_agent_config(root, agent)

        runtime_dir, builtin_dir, selected_skills_dir = manager.create_runtime_workspace(root, agent)
        try:
            assert (selected_skills_dir / "local-skill" / "SKILL.md").exists()
            assert not (runtime_dir / "skills" / "local-skill" / "SKILL.md").exists()
            assert list(builtin_dir.iterdir()) == []
        finally:
            shutil_rmtree(runtime_dir)
    finally:
        manager.cleanup_workspace(root)


def test_runtime_persist_propagates_deletions_and_skill_edits(tmp_path: Path):
    store = MemoryStore()
    manager = CloudWorkspaceManager(
        store=store,
        cache_root=tmp_path,
        workspace_prefix="workspaces",
        platform_provider=ManagedProviderView(provider="openrouter", model="openai/gpt-4.1"),
    )

    root = manager.ensure_user_workspace("alice")
    try:
        note = root / "notes.txt"
        note.write_text("keep me?", encoding="utf-8")
        custom_skill = root / "skills" / "workspace-skill"
        custom_skill.mkdir(parents=True)
        (custom_skill / "SKILL.md").write_text("# before", encoding="utf-8")
        manager.upload_user_workspace("alice", root)

        agent = manager.load_agent_config(root, "default")
        agent.skills = ["workspace-skill"]
        manager.save_agent_config(root, agent)
        runtime_dir, _, selected_skills_dir = manager.create_runtime_workspace(root, agent)
        try:
            (runtime_dir / "notes.txt").unlink()
            (selected_skills_dir / "workspace-skill" / "SKILL.md").write_text("# after", encoding="utf-8")
            manager.persist_runtime_workspace(root, runtime_dir)
            manager.upload_user_workspace("alice", root)
        finally:
            shutil_rmtree(runtime_dir)

        assert not (root / "notes.txt").exists()
        assert (root / "skills" / "workspace-skill" / "SKILL.md").read_text(encoding="utf-8") == "# after"
        assert "workspaces/alice/notes.txt" not in store.data
    finally:
        manager.cleanup_workspace(root)


def test_effective_config_applies_agent_overrides(tmp_path: Path):
    settings_path = tmp_path / "platform.json"
    settings_path.write_text(
        '{"providers":{"openrouter":{"apiKey":"sk-test"}},"agents":{"defaults":{"model":"openai/gpt-4.1","maxToolIterations":200}}}',
        encoding="utf-8",
    )
    manager = CloudWorkspaceManager(
        store=MemoryStore(),
        cache_root=tmp_path,
        workspace_prefix="workspaces",
        platform_provider=ManagedProviderView(provider="openrouter", model="openai/gpt-4.1"),
    )
    service = CloudRuntimeService(
        settings=type("Settings", (), {"request_timeout": 30, "redis": type("RedisCfg", (), {"lock_ttl_s": 30})()})(),
        workspace_manager=manager,
        platform_config_path=settings_path,
        session_store=InMemorySessionStore(),
        lock_manager=InMemoryLockManager(),
    )
    root = manager.ensure_user_workspace("alice")
    try:
        agent = manager.load_agent_config(root, "default")
    finally:
        manager.cleanup_workspace(root)
    agent.max_tool_iterations = 33
    agent.reasoning_effort = "high"
    agent.timezone = "Asia/Shanghai"

    effective = service._build_effective_config(tmp_path / "runtime", agent)

    assert effective.agents.defaults.max_tool_iterations == 33
    assert effective.agents.defaults.reasoning_effort == "high"
    assert effective.agents.defaults.timezone == "Asia/Shanghai"


def test_runtime_workspace_hides_unselected_skills(tmp_path: Path):
    manager = CloudWorkspaceManager(
        store=MemoryStore(),
        cache_root=tmp_path,
        workspace_prefix="workspaces",
        platform_provider=ManagedProviderView(provider="openrouter", model="openai/gpt-4.1"),
    )

    root = manager.ensure_user_workspace("alice")
    try:
        workspace_skill = root / "skills" / "workspace-skill"
        workspace_skill.mkdir(parents=True)
        (workspace_skill / "SKILL.md").write_text("# hidden", encoding="utf-8")
        agent = manager.load_agent_config(root, "default")
        agent.skills = []
        manager.save_agent_config(root, agent)

        runtime_dir, _, selected_skills_dir = manager.create_runtime_workspace(root, agent)
        try:
            assert not (runtime_dir / "skills" / "workspace-skill" / "SKILL.md").exists()
            assert not list(selected_skills_dir.glob("*/SKILL.md"))
        finally:
            shutil_rmtree(runtime_dir)
    finally:
        manager.cleanup_workspace(root)


@pytest.mark.asyncio
async def test_multi_instance_flow_reuses_online_session(tmp_path: Path):
    store = MemoryStore()
    session_store = InMemorySessionStore()
    lock_manager = InMemoryLockManager()
    settings_path = tmp_path / "platform.json"
    settings_path.write_text(
        json.dumps(
            {
                "providers": {"openrouter": {"apiKey": "sk-test"}},
                "agents": {"defaults": {"model": "openai/gpt-4.1"}},
            }
        ),
        encoding="utf-8",
    )

    observed_contents: list[str] = []

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
        path = session_file_path(runtime_dir, session_key)
        prior = path.read_text(encoding="utf-8") if path.exists() else ""
        observed_contents.append(prior)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(prior + content, encoding="utf-8")
        return CloudChatResult(content="ok", model="openai/gpt-4.1")

    settings = type(
        "Settings",
        (),
        {
            "request_timeout": 30,
            "redis": type("RedisCfg", (), {"lock_ttl_s": 30})(),
        },
    )()

    service_a = CloudRuntimeService(
        settings=settings,
        workspace_manager=CloudWorkspaceManager(
            store=store,
            cache_root=tmp_path / "a",
            workspace_prefix="workspaces",
            platform_provider=ManagedProviderView(provider="openrouter", model="openai/gpt-4.1"),
        ),
        platform_config_path=settings_path,
        session_store=session_store,
        lock_manager=lock_manager,
        executor=executor,
    )
    service_b = CloudRuntimeService(
        settings=settings,
        workspace_manager=CloudWorkspaceManager(
            store=store,
            cache_root=tmp_path / "b",
            workspace_prefix="workspaces",
            platform_provider=ManagedProviderView(provider="openrouter", model="openai/gpt-4.1"),
        ),
        platform_config_path=settings_path,
        session_store=session_store,
        lock_manager=lock_manager,
        executor=executor,
    )
    user = AuthenticatedUser(user_id="alice", claims={"sub": "alice"}, token="t")

    token_a = await service_a.acquire_chat_lock("alice", "default", "thread-1")
    assert token_a is not None
    await service_a.run_chat(
        user=user,
        agent_name="default",
        session_id="thread-1",
        content="hello",
        lock_token=token_a,
    )

    token_b = await service_b.acquire_chat_lock("alice", "default", "thread-1")
    assert token_b is not None
    await service_b.run_chat(
        user=user,
        agent_name="default",
        session_id="thread-1",
        content=" world",
        lock_token=token_b,
    )

    assert observed_contents[0] == ""
    assert "hello" in observed_contents[1]


def shutil_rmtree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)
