"""Integration tests for CloudStorage with MemoryStore and SessionManager.

These tests verify the integration wiring with cloud_config passed through
the component chain. When cloud_config is None, LocalStorage is used internally
by MemoryStore and SessionManager (S3CompatibleStorage is only used when a real
cloud_config is provided, which requires a real S3-compatible endpoint).
"""

import pytest

from nanobot.config.schema import CloudStorageConfig
from nanobot.providers.cloud_storage import create_storage, LocalStorage
from nanobot.agent.memory import MemoryStore
from nanobot.session.manager import SessionManager


class TestMemoryStoreLocalIntegration:
    """Test MemoryStore integration using LocalStorage (cloud_config=None)."""

    def test_memory_store_full_cycle(self, tmp_path):
        """Test MemoryStore read/write cycle through LocalStorage."""
        # cloud_config=None uses LocalStorage internally
        # (S3CompatibleStorage only used when cloud_config is provided with real credentials)
        store = MemoryStore(tmp_path, cloud_config=None)

        # Write and read memory
        store.write_memory("# Test Memory\nSome facts here.")
        assert store.read_memory() == "# Test Memory\nSome facts here."

        # Write and read soul
        store.write_soul("You are a helpful assistant.")
        assert store.read_soul() == "You are a helpful assistant."

        # Write and read user
        store.write_user("The user's name is Alice.")
        assert store.read_user() == "The user's name is Alice."

        # Append history
        cursor = store.append_history("User said hello")
        assert cursor == 1

        # Verify storage exists
        assert store._exists("memory/MEMORY.md") is True
        assert store._exists("SOUL.md") is True
        assert store._exists("USER.md") is True
        assert store._exists("memory/history.jsonl") is True


class TestSessionManagerLocalIntegration:
    """Test SessionManager integration using LocalStorage (cloud_config=None)."""

    def test_session_manager_full_cycle(self, tmp_path):
        """Test SessionManager save/load cycle through LocalStorage."""
        # cloud_config=None uses LocalStorage internally
        mgr = SessionManager(tmp_path, cloud_config=None)

        # Create and save a session
        session = mgr.get_or_create("telegram:12345")
        session.add_message("user", "Hello")
        session.add_message("assistant", "Hi there!")
        mgr.save(session)

        # Load the session back
        loaded = mgr.get_or_create("telegram:12345")
        assert len(loaded.messages) == 2
        assert loaded.messages[0]["content"] == "Hello"
        assert loaded.messages[1]["content"] == "Hi there!"

        # Verify storage
        assert mgr._session_exists("telegram:12345") is True


class TestStorageFactoryIntegration:
    """Test create_storage factory integration."""

    def test_returns_local_when_config_none(self, tmp_path):
        """create_storage returns LocalStorage when cloud_config is None."""
        storage = create_storage(None, tmp_path)
        assert isinstance(storage, LocalStorage)

        storage.write("test.txt", b"hello")
        assert storage.read("test.txt") == b"hello"
