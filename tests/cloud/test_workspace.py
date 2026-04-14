from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

import pytest

from nanobot.cloud.auth import AuthenticatedUser
from nanobot.cloud.config import CloudAgentConfig, ManagedProviderView, SkillCacheSettings
from nanobot.cloud.session_sanitize import sanitize_session_payload_for_persist
from nanobot.cloud.runtime import CloudChatResult, CloudRuntimeService, CloudWorkspaceManager
from nanobot.cloud.session_store import InMemorySessionStore, session_file_path
from nanobot.cloud.skills_cache import InMemorySkillBundleStore
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


def test_upload_user_workspace_publishes_workspace_config_last_and_cleans_stale_keys(tmp_path: Path):
    store = MemoryStore()
    manager = CloudWorkspaceManager(
        store=store,
        cache_root=tmp_path,
        workspace_prefix="workspaces",
        platform_provider=ManagedProviderView(provider="openrouter", model="openai/gpt-4.1"),
    )

    root = manager.ensure_user_workspace("alice")
    try:
        cfg = manager.load_workspace_config(root)
        cfg.agents["research"] = "agents/research/config.json"
        manager.save_workspace_config(root, cfg)
        manager.save_agent_config(root, CloudAgentConfig(name="research"))
        stale_key = "workspaces/alice/stale.txt"
        store.put_bytes(stale_key, b"old")
        store.operations.clear()

        manager.upload_user_workspace("alice", root)

        ops = store.operations
        config_key = manager.workspace_config_key("alice")
        put_indices = [i for i, (op, key) in enumerate(ops) if op == "put" and key == config_key]
        delete_indices = [i for i, (op, key) in enumerate(ops) if op == "delete" and key == stale_key]

        assert put_indices
        assert delete_indices
        assert put_indices[-1] < delete_indices[0]
        assert stale_key not in store.data
    finally:
        manager.cleanup_workspace(root)


def test_first_login_workspace_estimate_is_non_zero(tmp_path: Path):
    manager = CloudWorkspaceManager(
        store=MemoryStore(),
        cache_root=tmp_path,
        workspace_prefix="workspaces",
        platform_provider=ManagedProviderView(provider="openrouter", model="openai/gpt-4.1"),
    )

    assert manager.estimate_workspace_bytes("alice") > 0


def test_first_login_workspace_estimate_covers_materialized_workspace(tmp_path: Path):
    manager = CloudWorkspaceManager(
        store=MemoryStore(),
        cache_root=tmp_path,
        workspace_prefix="workspaces",
        platform_provider=ManagedProviderView(provider="openrouter", model="openai/gpt-4.1"),
    )

    estimated = manager.estimate_workspace_bytes("alice")
    root = manager.ensure_user_workspace("alice")
    try:
        actual = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
        assert estimated >= actual
    finally:
        manager.cleanup_workspace(root)


@pytest.mark.asyncio
async def test_runtime_materialization_only_keeps_selected_skills(tmp_path: Path):
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

        runtime_dir, builtin_dir, selected_skills_dir, total_bytes = await manager.create_runtime_workspace(
            root,
            agent,
            bundle_store=InMemorySkillBundleStore(),
        )
        try:
            assert (selected_skills_dir / "local-skill" / "SKILL.md").exists()
            assert not (runtime_dir / "skills" / "local-skill" / "SKILL.md").exists()
            assert list(builtin_dir.iterdir()) == []
            assert total_bytes > 0
        finally:
            shutil_rmtree(runtime_dir)
    finally:
        manager.cleanup_workspace(root)


@pytest.mark.asyncio
async def test_runtime_persist_propagates_deletions_and_skill_edits(tmp_path: Path):
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
        runtime_dir, _, selected_skills_dir, _ = await manager.create_runtime_workspace(
            root,
            agent,
            bundle_store=InMemorySkillBundleStore(),
        )
        try:
            (runtime_dir / "notes.txt").unlink()
            (selected_skills_dir / "workspace-skill" / "SKILL.md").write_text("# after", encoding="utf-8")
            manager.persist_runtime_workspace(root, runtime_dir, agent.name)
            manager.upload_user_workspace("alice", root)
        finally:
            shutil_rmtree(runtime_dir)

        assert not (root / "notes.txt").exists()
        assert (root / "skills" / "workspace-skill" / "SKILL.md").read_text(encoding="utf-8") == "# after"
        assert "workspaces/alice/notes.txt" not in store.data
    finally:
        manager.cleanup_workspace(root)


@pytest.mark.asyncio
async def test_runtime_persist_propagates_new_workspace_skill_creations(tmp_path: Path):
    store = MemoryStore()
    manager = CloudWorkspaceManager(
        store=store,
        cache_root=tmp_path,
        workspace_prefix="workspaces",
        platform_provider=ManagedProviderView(provider="openrouter", model="openai/gpt-4.1"),
    )

    root = manager.ensure_user_workspace("alice")
    try:
        agent = manager.load_agent_config(root, "default")
        runtime_dir, _, _, _ = await manager.create_runtime_workspace(
            root,
            agent,
            bundle_store=InMemorySkillBundleStore(),
        )
        try:
            created_skill = runtime_dir / "skills" / "new-skill"
            created_skill.mkdir(parents=True)
            (created_skill / "SKILL.md").write_text("# new workspace skill", encoding="utf-8")
            (created_skill / "scripts" / "run.sh").parent.mkdir(parents=True, exist_ok=True)
            (created_skill / "scripts" / "run.sh").write_text("echo hi\n", encoding="utf-8")

            manager.persist_runtime_workspace(root, runtime_dir, agent.name)
            manager.upload_user_workspace("alice", root)
        finally:
            shutil_rmtree(runtime_dir)

        assert (root / "skills" / "new-skill" / "SKILL.md").read_text(encoding="utf-8") == "# new workspace skill"
        assert (root / "skills" / "new-skill" / "scripts" / "run.sh").read_text(encoding="utf-8") == "echo hi\n"
        assert "workspaces/alice/skills/new-skill/SKILL.md" in store.data
        refreshed = manager.load_agent_config(root, "default")
        assert "new-skill" in refreshed.skills

        next_runtime_dir, _, next_selected_skills_dir, _ = await manager.create_runtime_workspace(
            root,
            refreshed,
            bundle_store=InMemorySkillBundleStore(),
        )
        try:
            assert (next_selected_skills_dir / "new-skill" / "SKILL.md").exists()
            manifest = json.loads((next_selected_skills_dir / "manifest.json").read_text(encoding="utf-8"))
            assert [skill["skill_name"] for skill in manifest["skills"]] == ["new-skill"]
        finally:
            shutil_rmtree(next_runtime_dir)
    finally:
        manager.cleanup_workspace(root)


@pytest.mark.asyncio
async def test_runtime_persist_propagates_new_agent_skill_creations(tmp_path: Path):
    store = MemoryStore()
    manager = CloudWorkspaceManager(
        store=store,
        cache_root=tmp_path,
        workspace_prefix="workspaces",
        platform_provider=ManagedProviderView(provider="openrouter", model="openai/gpt-4.1"),
    )

    root = manager.ensure_user_workspace("alice")
    try:
        agent = manager.load_agent_config(root, "default")
        runtime_dir, _, _, _ = await manager.create_runtime_workspace(
            root,
            agent,
            bundle_store=InMemorySkillBundleStore(),
        )
        try:
            created_skill = runtime_dir / "agents" / "default" / "skills" / "agent-skill"
            created_skill.mkdir(parents=True)
            (created_skill / "SKILL.md").write_text("# new agent skill", encoding="utf-8")

            manager.persist_runtime_workspace(root, runtime_dir, agent.name)
            manager.upload_user_workspace("alice", root)
        finally:
            shutil_rmtree(runtime_dir)

        assert (
            root / "agents" / "default" / "skills" / "agent-skill" / "SKILL.md"
        ).read_text(encoding="utf-8") == "# new agent skill"
        assert "workspaces/alice/agents/default/skills/agent-skill/SKILL.md" in store.data
        refreshed = manager.load_agent_config(root, "default")
        assert "agent-skill" in refreshed.skills
    finally:
        manager.cleanup_workspace(root)


def test_effective_config_applies_agent_overrides(tmp_path: Path):
    settings_path = tmp_path / "platform.json"
    settings_path.write_text(
        (
            '{"providers":{"openrouter":{"apiKey":"sk-test"}},'
            '"agents":{"defaults":{"model":"openai/gpt-4.1","maxToolIterations":200}},'
            '"tools":{"restrictToWorkspace":false}}'
        ),
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
    assert effective.tools.restrict_to_workspace is True


def test_sanitize_session_payload_rewrites_runtime_checkpoint_paths(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "runtime"
    payload = (
        json.dumps(
            {
                "_type": "metadata",
                "metadata": {
                    "runtime_checkpoint": {
                        "assistant_message": {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": json.dumps({"path": str(runtime_dir / "USER.md")}),
                                    },
                                }
                            ],
                        },
                        "pending_tool_calls": [
                            {
                                "id": "call-2",
                                "type": "function",
                                "function": {
                                    "name": "exec",
                                    "arguments": json.dumps({"cwd": str(runtime_dir), "path": str(runtime_dir / "USER.md")}),
                                },
                            }
                        ],
                    }
                },
            },
            ensure_ascii=False,
        )
        + "\n"
    ).encode("utf-8")

    sanitized = sanitize_session_payload_for_persist(payload, runtime_dir)
    decoded = sanitized.decode("utf-8")
    loaded = json.loads(decoded)
    pending = loaded["metadata"]["runtime_checkpoint"]["pending_tool_calls"][0]["function"]["arguments"]
    assistant = loaded["metadata"]["runtime_checkpoint"]["assistant_message"]["tool_calls"][0]["function"]["arguments"]

    assert str(runtime_dir) not in decoded
    assert json.loads(assistant)["path"] == "USER.md"
    assert json.loads(pending)["cwd"] == "."
    assert json.loads(pending)["path"] == "USER.md"


@pytest.mark.asyncio
async def test_runtime_workspace_hides_unselected_skills(tmp_path: Path):
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

        runtime_dir, _, selected_skills_dir, _ = await manager.create_runtime_workspace(
            root,
            agent,
            bundle_store=InMemorySkillBundleStore(),
        )
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
        message_id=None,
        on_stream=None,
        on_stream_end=None,
        on_tool_event=None,
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
            "skill_cache": SkillCacheSettings(),
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
        skill_bundle_store=InMemorySkillBundleStore(),
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
        skill_bundle_store=InMemorySkillBundleStore(),
        executor=executor,
    )
    user = AuthenticatedUser(user_id="alice", claims={"sub": "alice"}, token="t")

    reservation_a = await service_a.reserve_chat_execution("alice", "default", "thread-1")
    await service_a.run_chat(
        user=user,
        agent_name="default",
        session_id="thread-1",
        content="hello",
        reservation=reservation_a,
    )

    reservation_b = await service_b.reserve_chat_execution("alice", "default", "thread-1")
    await service_b.run_chat(
        user=user,
        agent_name="default",
        session_id="thread-1",
        content=" world",
        reservation=reservation_b,
    )

    assert observed_contents[0] == ""
    assert "hello" in observed_contents[1]


@pytest.mark.asyncio
async def test_online_session_persist_rewrites_runtime_absolute_paths_to_relative(tmp_path: Path):
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
        del root, builtin_dir, selected_skills_dir, user, agent, content, message_id, on_stream, on_stream_end, on_tool_event
        path = session_file_path(runtime_dir, session_key)
        session_payload = [
            {
                "_type": "metadata",
                "key": session_key,
                "created_at": "2026-04-13T00:00:00",
                "updated_at": "2026-04-13T00:00:00",
                "metadata": {},
                "last_consolidated": 0,
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-user-md",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": json.dumps({"path": str(runtime_dir / "USER.md")}),
                        },
                    }
                ],
            },
        ]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(json.dumps(line, ensure_ascii=False) for line in session_payload) + "\n", encoding="utf-8")
        return CloudChatResult(content="ok", model="openai/gpt-4.1")

    settings = type(
        "Settings",
        (),
        {
            "request_timeout": 30,
            "redis": type("RedisCfg", (), {"lock_ttl_s": 30})(),
            "skill_cache": SkillCacheSettings(),
        },
    )()
    service = CloudRuntimeService(
        settings=settings,
        workspace_manager=CloudWorkspaceManager(
            store=store,
            cache_root=tmp_path / "cache",
            workspace_prefix="workspaces",
            platform_provider=ManagedProviderView(provider="openrouter", model="openai/gpt-4.1"),
        ),
        platform_config_path=settings_path,
        session_store=session_store,
        lock_manager=lock_manager,
        skill_bundle_store=InMemorySkillBundleStore(),
        executor=executor,
    )

    user = AuthenticatedUser(user_id="alice", claims={"sub": "alice"}, token="t")
    reservation = await service.reserve_chat_execution("alice", "default", "thread-1")
    await service.run_chat(
        user=user,
        agent_name="default",
        session_id="thread-1",
        content="hello",
        reservation=reservation,
    )

    persisted_raw = await session_store.load(service._session_key("alice", "default", "thread-1"))
    assert persisted_raw is not None
    persisted = persisted_raw.decode("utf-8")
    loaded = [json.loads(line) for line in persisted.splitlines() if line.strip()]
    arguments = loaded[1]["tool_calls"][0]["function"]["arguments"]
    assert json.loads(arguments)["path"] == "USER.md"
    assert "/runtime" not in persisted


@pytest.mark.asyncio
async def test_cloud_multiturn_user_md_edits_stay_in_current_user_workspace(tmp_path: Path):
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

    manager = CloudWorkspaceManager(
        store=store,
        cache_root=tmp_path / "cache",
        workspace_prefix="workspaces",
        platform_provider=ManagedProviderView(provider="openrouter", model="openai/gpt-4.1"),
    )
    alice_root = manager.ensure_user_workspace("alice")
    bob_root = manager.ensure_user_workspace("bob")
    try:
        (alice_root / "USER.md").write_text("alice original\n", encoding="utf-8")
        (bob_root / "USER.md").write_text("bob original\n", encoding="utf-8")
        manager.upload_user_workspace("alice", alice_root)
        manager.upload_user_workspace("bob", bob_root)
    finally:
        manager.cleanup_workspace(alice_root)

    try:
        run_count = 0

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
            nonlocal run_count
            del builtin_dir, selected_skills_dir, agent, content, message_id, on_stream, on_stream_end, on_tool_event
            path = session_file_path(runtime_dir, session_key)
            payload_lines: list[dict[str, object]] = []
            if path.exists():
                payload_lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            tool_path = None
            for line in payload_lines:
                for tool_call in line.get("tool_calls", []):
                    function = tool_call.get("function") or {}
                    args = json.loads(function.get("arguments") or "{}")
                    tool_path = args.get("path")
            if run_count == 0:
                tool_path = str(runtime_dir / "USER.md")
            assert tool_path is not None
            target = Path(tool_path) if Path(tool_path).is_absolute() else runtime_dir / tool_path
            target.write_text(f"{user.user_id} updated round {run_count + 1}\n", encoding="utf-8")

            session_payload = [
                {
                    "_type": "metadata",
                    "key": session_key,
                    "created_at": "2026-04-13T00:00:00",
                    "updated_at": "2026-04-13T00:00:00",
                    "metadata": {},
                    "last_consolidated": 0,
                },
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-user-md",
                            "type": "function",
                            "function": {
                                "name": "edit_file",
                                "arguments": json.dumps({"path": tool_path}),
                            },
                        }
                    ],
                },
            ]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(json.dumps(line, ensure_ascii=False) for line in session_payload) + "\n", encoding="utf-8")
            run_count += 1
            return CloudChatResult(content="ok", model="openai/gpt-4.1")

        settings = type(
            "Settings",
            (),
            {
                "request_timeout": 30,
                "redis": type("RedisCfg", (), {"lock_ttl_s": 30})(),
                "skill_cache": SkillCacheSettings(),
            },
        )()
        service = CloudRuntimeService(
            settings=settings,
            workspace_manager=manager,
            platform_config_path=settings_path,
            session_store=session_store,
            lock_manager=lock_manager,
            skill_bundle_store=InMemorySkillBundleStore(),
            executor=executor,
        )
        user = AuthenticatedUser(user_id="alice", claims={"sub": "alice"}, token="t")

        reservation_a = await service.reserve_chat_execution("alice", "default", "thread-1")
        await service.run_chat(
            user=user,
            agent_name="default",
            session_id="thread-1",
            content="first",
            reservation=reservation_a,
        )

        reservation_b = await service.reserve_chat_execution("alice", "default", "thread-1")
        await service.run_chat(
            user=user,
            agent_name="default",
            session_id="thread-1",
            content="second",
            reservation=reservation_b,
        )

        alice_checkout = manager.ensure_user_workspace("alice")
        try:
            assert "alice updated round 2" in (alice_checkout / "USER.md").read_text(encoding="utf-8")
        finally:
            manager.cleanup_workspace(alice_checkout)
    finally:
        bob_checkout = manager.ensure_user_workspace("bob")
        try:
            assert (bob_checkout / "USER.md").read_text(encoding="utf-8") == "bob original\n"
        finally:
            manager.cleanup_workspace(bob_checkout)
            manager.cleanup_workspace(bob_root)


@pytest.mark.asyncio
async def test_run_chat_waits_for_inflight_bootstrap_task(tmp_path: Path, monkeypatch):
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
        return CloudChatResult(content=f"reply:{content}", model="openai/gpt-4.1")

    settings = type(
        "Settings",
        (),
        {
            "request_timeout": 30,
            "redis": type("RedisCfg", (), {"lock_ttl_s": 30})(),
            "skill_cache": SkillCacheSettings(),
        },
    )()
    manager = CloudWorkspaceManager(
        store=store,
        cache_root=tmp_path / "cache",
        workspace_prefix="workspaces",
        platform_provider=ManagedProviderView(provider="openrouter", model="openai/gpt-4.1"),
    )
    service = CloudRuntimeService(
        settings=settings,
        workspace_manager=manager,
        platform_config_path=settings_path,
        session_store=session_store,
        lock_manager=lock_manager,
        skill_bundle_store=InMemorySkillBundleStore(),
        executor=executor,
    )
    user = AuthenticatedUser(user_id="alice", claims={"sub": "alice"}, token="t")

    started = threading.Event()
    release = threading.Event()
    calls = 0
    original = manager.bootstrap_user_workspace

    def slow_bootstrap(user_id: str) -> bool:
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=2)
        return original(user_id)

    monkeypatch.setattr(manager, "bootstrap_user_workspace", slow_bootstrap)

    agents = await service.list_agents(user)
    assert [agent.name for agent in agents] == ["default"]
    assert await asyncio.to_thread(started.wait, 1)

    reservation = await service.reserve_chat_execution("alice", "default", "thread-1")
    chat_task = asyncio.create_task(
        service.run_chat(
            user=user,
            agent_name="default",
            session_id="thread-1",
            content="hello",
            reservation=reservation,
        )
    )

    await asyncio.sleep(0.05)
    assert not chat_task.done()
    release.set()
    result = await chat_task

    assert result.content == "reply:hello"
    assert calls == 1


def shutil_rmtree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)
