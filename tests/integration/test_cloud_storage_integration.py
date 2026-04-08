"""Integration tests for CloudStorage with MemoryStore and SessionManager using moto."""

import pytest
from moto import mock_aws

from nanobot.config.schema import CloudStorageConfig
from nanobot.providers.cloud_storage import S3CompatibleStorage, create_storage
from nanobot.agent.memory import MemoryStore
from nanobot.session.manager import SessionManager


@pytest.fixture
def cloud_config():
    return CloudStorageConfig(
        provider="cos",
        endpoint_url="https://cos.ap-beijing.myqcloud.com",
        bucket="test-bucket",
        region="ap-beijing",
        secret_id="test-id",
        secret_key="test-key",
        prefix="mclaw/",
    )


@mock_aws
def test_memory_store_full_cycle(cloud_config, tmp_path):
    """Test MemoryStore read/write cycle through CloudStorage."""
    import boto3
    client = boto3.client(
        "s3",
        endpoint_url="https://cos.ap-beijing.myqcloud.com",
        aws_access_key_id="test-id",
        aws_secret_access_key="test-key",
    )
    client.create_bucket(Bucket="test-bucket")

    store = MemoryStore(tmp_path, cloud_config=cloud_config)

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


@mock_aws
def test_session_manager_full_cycle(cloud_config, tmp_path):
    """Test SessionManager save/load cycle through CloudStorage."""
    import boto3
    client = boto3.client(
        "s3",
        endpoint_url="https://cos.ap-beijing.myqcloud.com",
        aws_access_key_id="test-id",
        aws_secret_access_key="test-key",
    )
    client.create_bucket(Bucket="test-bucket")

    mgr = SessionManager(tmp_path, cloud_config=cloud_config)

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


@mock_aws
def test_storage_factory_local(cloud_config, tmp_path):
    """Test create_storage returns LocalStorage when cloud_config is None."""
    storage = create_storage(None, tmp_path)
    # Should be LocalStorage
    assert not isinstance(storage, S3CompatibleStorage)

    # LocalStorage should work normally
    storage.write("test.txt", b"hello")
    assert storage.read("test.txt") == b"hello"


@mock_aws
def test_storage_factory_cloud(cloud_config, tmp_path):
    """Test create_storage returns S3CompatibleStorage when cloud_config is set."""
    import boto3
    client = boto3.client(
        "s3",
        endpoint_url="https://cos.ap-beijing.myqcloud.com",
        aws_access_key_id="test-id",
        aws_secret_access_key="test-key",
    )
    client.create_bucket(Bucket="test-bucket")

    storage = create_storage(cloud_config, tmp_path)
    assert isinstance(storage, S3CompatibleStorage)

    storage.write("cloud.txt", b"cloud data")
    assert storage.exists("cloud.txt") is True
