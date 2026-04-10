"""Integration tests for multi-user workspace isolation."""

import asyncio
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from nanobot.agent.loop import AgentLoop
from nanobot.bus.queue import MessageBus
from nanobot.bus.events import InboundMessage
from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.utils.user_context import (
    set_current_user_id,
    clear_current_user_id,
)


class DummyProvider(LLMProvider):
    """Minimal provider for testing."""

    def __init__(self):
        super().__init__()

    @property
    def model_name(self) -> str:
        return "test"

    @property
    def provider_name(self) -> str:
        return "test"

    def get_default_model(self) -> str:
        return "test-model"

    async def chat(self, *args, **kwargs) -> LLMResponse:
        return LLMResponse(content="ok", tool_calls=[])


@pytest.mark.asyncio
async def test_user_context_set_in_dispatch(tmp_path):
    """Verify user context is set when processing a message."""
    bus = MessageBus()
    provider = DummyProvider()

    # Track calls to set_current_user_id
    captured_user_ids = []

    # Store original
    import nanobot.agent.loop as loop_module
    original_set_user = loop_module.set_current_user_id

    # Create a wrapper that tracks calls
    def tracking_set_user(user_id):
        captured_user_ids.append(user_id)
        original_set_user(user_id)

    # Also mock consolidator to avoid errors during message processing
    mock_consolidator = MagicMock()
    mock_consolidator.maybe_consolidate_by_tokens = AsyncMock()
    mock_consolidator.context_window_tokens = 1000

    async def run_test():
        # Patch where it's imported/used
        with patch.object(loop_module, 'set_current_user_id', tracking_set_user):
            loop = AgentLoop(bus=bus, provider=provider, workspace=tmp_path)
            loop.consolidator = mock_consolidator

            # Run the loop in a background task
            loop_task = asyncio.create_task(loop.run())

            # Publish a message while still inside the patch
            await bus.publish_inbound(InboundMessage(
                channel="test",
                sender_id="alice",
                chat_id="chat1",
                content="hello",
            ))

            # Wait for the message to be processed
            await asyncio.sleep(0.2)

            loop._running = False
            loop_task.cancel()
            try:
                await loop_task
            except asyncio.CancelledError:
                pass

        return captured_user_ids

    # Run the test coroutine
    captured_user_ids = await run_test()

    assert "alice" in captured_user_ids


@pytest.mark.asyncio
async def test_filesystem_path_injects_user_prefix(tmp_path):
    """Verify filesystem tool resolves paths with user prefix."""
    from nanobot.agent.tools.filesystem import ReadFileTool

    workspace = tmp_path / "workspaces" / "alice"
    workspace.mkdir(parents=True)

    tool = ReadFileTool(workspace=workspace)

    set_current_user_id("alice")
    try:
        # A relative path should get workspaces/alice/ prepended
        resolved = tool._resolve("myfile.txt")
        assert "workspaces/alice" in str(resolved)
    finally:
        clear_current_user_id()


@pytest.mark.asyncio
async def test_no_user_context_falls_back_to_workspace(tmp_path):
    """Without user context, paths resolve normally."""
    from nanobot.agent.tools.filesystem import ReadFileTool

    workspace = tmp_path
    tool = ReadFileTool(workspace=workspace)

    clear_current_user_id()
    resolved = tool._resolve("myfile.txt")
    assert "workspaces" not in str(resolved)


@pytest.mark.asyncio
async def test_filesystem_storage_key_is_user_scoped_once(tmp_path):
    from nanobot.agent.tools.filesystem import WriteFileTool

    tool = WriteFileTool(workspace=tmp_path)

    set_current_user_id("alice")
    try:
        key = tool._storage_key("USER.md")
        assert key == "workspaces/alice/USER.md"
    finally:
        clear_current_user_id()


@pytest.mark.asyncio
async def test_memory_store_user_md_writes_to_scoped_path(tmp_path):
    from nanobot.agent.memory import MemoryStore

    store = MemoryStore(tmp_path)

    set_current_user_id("alice")
    try:
        store.write_user("hello")
    finally:
        clear_current_user_id()

    assert (tmp_path / "workspaces" / "alice" / "USER.md").read_text(encoding="utf-8") == "hello"


@pytest.mark.asyncio
async def test_context_builder_bootstrap_reads_user_md(tmp_path):
    from nanobot.agent.context import ContextBuilder

    user_dir = tmp_path / "workspaces" / "alice"
    user_dir.mkdir(parents=True)
    (user_dir / "USER.md").write_text("alice-user", encoding="utf-8")

    builder = ContextBuilder(tmp_path)

    set_current_user_id("alice")
    try:
        prompt = builder.build_system_prompt(channel="test")
    finally:
        clear_current_user_id()

    assert "alice-user" in prompt
