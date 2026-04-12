from __future__ import annotations

from pathlib import Path

from nanobot.cloud.config import ManagedProviderView
from nanobot.cloud.runtime import CloudRuntimeService, CloudWorkspaceManager
from tests.cloud.support import MemoryStore


def test_first_login_bootstraps_workspace(tmp_path: Path):
    manager = CloudWorkspaceManager(
        store=MemoryStore(),
        cache_root=tmp_path,
        workspace_prefix="workspaces",
        platform_provider=ManagedProviderView(provider="openrouter", model="openai/gpt-4.1"),
    )

    root = manager.ensure_user_workspace("alice")
    config = manager.load_workspace_config(root)
    agent = manager.load_agent_config(root, "default")

    assert config.user_id == "alice"
    assert config.default_agent == "default"
    assert "default" in config.agents
    assert agent.name == "default"
    assert (root / "memory" / "MEMORY.md").exists()


def test_runtime_materialization_only_keeps_selected_skills(tmp_path: Path):
    store = MemoryStore()
    manager = CloudWorkspaceManager(
        store=store,
        cache_root=tmp_path,
        workspace_prefix="workspaces",
        platform_provider=ManagedProviderView(provider="openrouter", model="openai/gpt-4.1"),
    )

    root = manager.ensure_user_workspace("alice")
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
        manager.persist_runtime_workspace(root, runtime_dir)


def test_runtime_persist_propagates_deletions_and_skill_edits(tmp_path: Path):
    store = MemoryStore()
    manager = CloudWorkspaceManager(
        store=store,
        cache_root=tmp_path,
        workspace_prefix="workspaces",
        platform_provider=ManagedProviderView(provider="openrouter", model="openai/gpt-4.1"),
    )

    root = manager.ensure_user_workspace("alice")
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
    (runtime_dir / "notes.txt").unlink()
    (selected_skills_dir / "workspace-skill" / "SKILL.md").write_text("# after", encoding="utf-8")

    manager.persist_runtime_workspace(root, runtime_dir)
    manager.upload_user_workspace("alice", root)

    assert not (root / "notes.txt").exists()
    assert (root / "skills" / "workspace-skill" / "SKILL.md").read_text(encoding="utf-8") == "# after"
    assert "workspaces/alice/notes.txt" not in store.data


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
        settings=type("Settings", (), {"request_timeout": 30})(),
        workspace_manager=manager,
        platform_config_path=settings_path,
    )
    agent = manager.load_agent_config(manager.ensure_user_workspace("alice"), "default")
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
        manager.persist_runtime_workspace(root, runtime_dir)
