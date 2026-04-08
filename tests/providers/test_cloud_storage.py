"""Tests for S3CompatibleStorage using moto mock."""

import pytest
from moto import mock_aws

from nanobot.config.schema import CloudStorageConfig
from nanobot.providers.cloud_storage import S3CompatibleStorage


@pytest.fixture
def aws_config():
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
def test_write_and_read(aws_config):
    import boto3
    client = boto3.client("s3",
        endpoint_url="https://cos.ap-beijing.myqcloud.com",
        aws_access_key_id="test-id",
        aws_secret_access_key="test-key")
    client.create_bucket(Bucket="test-bucket")

    storage = S3CompatibleStorage(aws_config)
    storage.write("test/file.txt", b"hello world")
    assert storage.read("test/file.txt") == b"hello world"


@mock_aws
def test_read_nonexistent_raises(aws_config):
    import boto3
    client = boto3.client("s3",
        endpoint_url="https://cos.ap-beijing.myqcloud.com",
        aws_access_key_id="test-id",
        aws_secret_access_key="test-key")
    client.create_bucket(Bucket="test-bucket")

    storage = S3CompatibleStorage(aws_config)
    with pytest.raises(FileNotFoundError):
        storage.read("nonexistent/file.txt")


@mock_aws
def test_exists(aws_config):
    import boto3
    client = boto3.client("s3",
        endpoint_url="https://cos.ap-beijing.myqcloud.com",
        aws_access_key_id="test-id",
        aws_secret_access_key="test-key")
    client.create_bucket(Bucket="test-bucket")

    storage = S3CompatibleStorage(aws_config)
    assert storage.exists("test/file.txt") is False
    storage.write("test/file.txt", b"data")
    assert storage.exists("test/file.txt") is True


@mock_aws
def test_list(aws_config):
    import boto3
    client = boto3.client("s3",
        endpoint_url="https://cos.ap-beijing.myqcloud.com",
        aws_access_key_id="test-id",
        aws_secret_access_key="test-key")
    client.create_bucket(Bucket="test-bucket")

    storage = S3CompatibleStorage(aws_config)
    storage.write("dir/file1.txt", b"data1")
    storage.write("dir/file2.txt", b"data2")
    storage.write("other/file3.txt", b"data3")
    keys = sorted(storage.list("dir/"))
    assert keys == ["file1.txt", "file2.txt"]


@mock_aws
def test_delete(aws_config):
    import boto3
    client = boto3.client("s3",
        endpoint_url="https://cos.ap-beijing.myqcloud.com",
        aws_access_key_id="test-id",
        aws_secret_access_key="test-key")
    client.create_bucket(Bucket="test-bucket")

    storage = S3CompatibleStorage(aws_config)
    storage.write("to_delete.txt", b"data")
    assert storage.exists("to_delete.txt") is True
    storage.delete("to_delete.txt")
    assert storage.exists("to_delete.txt") is False


@mock_aws
def test_prefix_applied(aws_config):
    import boto3
    client = boto3.client("s3",
        endpoint_url="https://cos.ap-beijing.myqcloud.com",
        aws_access_key_id="test-id",
        aws_secret_access_key="test-key")
    client.create_bucket(Bucket="test-bucket")

    storage = S3CompatibleStorage(aws_config)
    storage.write("memory/history.jsonl", b"[]")

    # Verify prefix 'mclaw/' is prepended
    response = client.list_objects_v2(Bucket="test-bucket")
    keys = [obj["Key"] for obj in response.get("Contents", [])]
    assert "mclaw/memory/history.jsonl" in keys
