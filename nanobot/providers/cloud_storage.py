"""Cloud storage: interface + S3-compatible implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import ClientError

from nanobot.config.schema import CloudStorageConfig


class CloudStorage(Protocol):
    """Protocol for cloud storage backends."""

    def read(self, key: str) -> bytes:
        """Read a file and return its bytes content."""
        ...

    def write(self, key: str, data: bytes) -> None:
        """Write bytes content to a file."""
        ...

    def list(self, prefix: str) -> list[str]:
        """List all keys under a prefix. Returns relative key list."""
        ...

    def exists(self, key: str) -> bool:
        """Check if a key exists."""
        ...

    def delete(self, key: str) -> None:
        """Delete a key."""
        ...


class S3CompatibleStorage:
    """S3-compatible storage backend (supports COS, MinIO, AWS S3, etc.)."""

    def __init__(self, config: CloudStorageConfig):
        self._prefix = config.prefix
        self._bucket = config.bucket
        self._client = boto3.client(
            "s3",
            endpoint_url=config.endpoint_url or None,
            aws_access_key_id=config.secret_id,
            aws_secret_access_key=config.secret_key,
            region_name=config.region or None,
            config=BotoConfig(signature_version="s3v4"),
        )

    def _full_key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    def read(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=self._full_key(key))
            return response["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                raise FileNotFoundError(f"Key not found: {key}") from e
            raise

    def write(self, key: str, data: bytes) -> None:
        self._client.put_object(Bucket=self._bucket, Key=self._full_key(key), Body=data)

    def list(self, prefix: str) -> list[str]:
        full_prefix = self._full_key(prefix)
        keys: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=full_prefix):
            for obj in page.get("Contents", []):
                key = obj["Key"]
                if key.startswith(full_prefix):
                    relative = key[len(full_prefix):]
                    if relative:
                        keys.append(relative)
        return keys

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=self._full_key(key))
            return True
        except ClientError:
            return False

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=self._full_key(key))


class LocalStorage:
    """Local filesystem storage (fallback when no cloud_storage configured)."""

    def __init__(self, workspace: "Path"):
        self._workspace = Path(workspace)

    def read(self, key: str) -> bytes:
        path = self._workspace / key
        if not path.is_file():
            raise FileNotFoundError(f"Key not found: {key}")
        return path.read_bytes()

    def write(self, key: str, data: bytes) -> None:
        path = self._workspace / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def list(self, prefix: str) -> list[str]:
        base = self._workspace / prefix
        if not base.is_dir():
            return []
        keys: list[str] = []
        for path in base.rglob("*"):
            if path.is_file():
                rel = str(path.relative_to(base))
                keys.append(rel)
        return keys

    def exists(self, key: str) -> bool:
        return (self._workspace / key).is_file()

    def delete(self, key: str) -> None:
        path = self._workspace / key
        if path.is_file():
            path.unlink()


def create_storage(config: CloudStorageConfig | None, workspace: "Path") -> CloudStorage:
    """Factory: return S3CompatibleStorage or LocalStorage based on config."""
    if config is None:
        return LocalStorage(workspace)
    return S3CompatibleStorage(config)
