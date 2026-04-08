"""Tests for CloudStorage providers."""

import pytest

from nanobot.config.schema import CloudStorageConfig
from nanobot.providers.cloud_storage import (
    LocalStorage,
    S3CompatibleStorage,
    create_storage,
)


class TestLocalStorage:
    """Test LocalStorage fallback."""

    def test_write_and_read(self, tmp_path):
        storage = LocalStorage(tmp_path)
        storage.write("test/file.txt", b"hello world")
        assert storage.read("test/file.txt") == b"hello world"

    def test_read_nonexistent_raises(self, tmp_path):
        storage = LocalStorage(tmp_path)
        with pytest.raises(FileNotFoundError):
            storage.read("nonexistent/file.txt")

    def test_exists(self, tmp_path):
        storage = LocalStorage(tmp_path)
        assert storage.exists("test/file.txt") is False
        storage.write("test/file.txt", b"data")
        assert storage.exists("test/file.txt") is True

    def test_list(self, tmp_path):
        storage = LocalStorage(tmp_path)
        storage.write("dir/file1.txt", b"data1")
        storage.write("dir/file2.txt", b"data2")
        storage.write("other/file3.txt", b"data3")
        keys = sorted(storage.list("dir/"))
        assert keys == ["file1.txt", "file2.txt"]

    def test_delete(self, tmp_path):
        storage = LocalStorage(tmp_path)
        storage.write("to_delete.txt", b"data")
        assert storage.exists("to_delete.txt") is True
        storage.delete("to_delete.txt")
        assert storage.exists("to_delete.txt") is False


class TestCreateStorage:
    """Test factory function."""

    def test_returns_local_when_config_none(self, tmp_path):
        storage = create_storage(None, tmp_path)
        assert isinstance(storage, LocalStorage)

    def test_returns_s3_compatible_when_config_provided(self):
        pytest.importorskip("boto3")
        config = CloudStorageConfig(
            provider="cos",
            endpoint_url="https://cos.ap-beijing.myqcloud.com",
            bucket="test-bucket",
            region="ap-beijing",
            secret_id="test-id",
            secret_key="test-key",
            prefix="mclaw/",
        )
        storage = create_storage(config, None)
        assert isinstance(storage, S3CompatibleStorage)
