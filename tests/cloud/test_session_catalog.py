from __future__ import annotations

import json
from pathlib import Path

from nanobot.cloud.config import CloudAgentConfig, ManagedProviderView
from nanobot.cloud.session_catalog import CloudSessionCatalog, session_messages_to_blocks
from nanobot.cloud.session_store import InMemorySessionStore
from nanobot.cloud.workspace_sync import RequestWorkspaceManager
from nanobot.session.manager import SessionManager
from tests.cloud.support import MemoryStore


def test_session_messages_to_blocks_merges_tool_results():
    messages = [
        {"role": "user", "content": "hi", "timestamp": "2026-04-12T14:00:00"},
        {
            "role": "assistant",
            "content": "",
            "timestamp": "2026-04-12T14:00:01",
            "tool_calls": [
                {
                    "id": "tc1",
                    "function": {"name": "read_file", "arguments": "{\"path\":\"README.md\"}"},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "tc1",
            "name": "read_file",
            "content": "README body",
            "timestamp": "2026-04-12T14:00:02",
        },
        {"role": "assistant", "content": "done", "timestamp": "2026-04-12T14:00:03"},
    ]

    rendered = session_messages_to_blocks(messages)

    assert [message["role"] for message in rendered] == ["user", "assistant", "assistant"]
    tool_block = rendered[1]["blocks"][0]
    assert tool_block["type"] == "tool_call"
    assert tool_block["toolName"] == "read_file"
    assert tool_block["resultText"] == "README body"


def test_catalog_list_reads_manifest_remotely_without_checkout(tmp_path: Path):
    store = MemoryStore()
    manager = RequestWorkspaceManager(
        store=store,
        cache_root=tmp_path,
        workspace_prefix="workspaces",
        platform_provider=ManagedProviderView(provider="managed", model="managed"),
    )
    root = manager.ensure_user_workspace("alice")
    try:
        cfg = manager.load_workspace_config(root)
        cfg.agents["research"] = "agents/research/config.json"
        manager.save_workspace_config(root, cfg)
        manager.save_agent_config(root, CloudAgentConfig(name="research"))
        session_manager = SessionManager(root)
        session = session_manager.get_or_create("cloud:alice:research:abc123")
        session.add_message("user", "hello world")
        session.metadata["title"] = "hello world"
        session_manager.save(session)
        catalog = CloudSessionCatalog(manager, InMemorySessionStore())
        catalog.sync_session_from_root(root, "alice", "research", "abc123")
        manager.upload_user_workspace("alice", root)
    finally:
        manager.cleanup_workspace(root)

    def fail(user_id: str):
        raise AssertionError(f"workspace checkout should not happen: {user_id}")

    manager.ensure_user_workspace = fail  # type: ignore[method-assign]
    catalog = CloudSessionCatalog(manager, InMemorySessionStore())

    items = catalog.list_sessions_remote("alice", "research")

    assert [item.id for item in items] == ["abc123"]
    assert items[0].title == "hello world"

    manifest_key = manager.user_prefix("alice") + "/sessions/index.json"
    manifest = json.loads(store.get_bytes(manifest_key).decode("utf-8"))
    assert manifest["sessions"]["abc123"]["agent_id"] == "research"
