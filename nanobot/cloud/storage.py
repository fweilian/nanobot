"""Object storage helpers for the cloud runtime."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol


class ObjectStore(Protocol):
    """Minimal object store protocol used by the cloud runtime."""

    def exists(self, key: str) -> bool: ...

    def list_keys(self, prefix: str) -> list[str]: ...

    def list_entries(self, prefix: str) -> list[tuple[str, int]]: ...

    def get_bytes(self, key: str) -> bytes: ...

    def put_bytes(self, key: str, data: bytes) -> None: ...

    def delete_keys(self, keys: list[str]) -> None: ...

    def delete_prefix(self, prefix: str) -> None: ...


class S3ObjectStore:
    """S3-compatible object store backed by boto3."""

    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "",
        endpoint_url: str | None = None,
        region_name: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
    ) -> None:
        import boto3

        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region_name,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )

    def _full_key(self, key: str) -> str:
        key = key.lstrip("/")
        return f"{self.prefix}/{key}" if self.prefix else key

    def exists(self, key: str) -> bool:
        full_key = self._full_key(key)
        try:
            self._client.head_object(Bucket=self.bucket, Key=full_key)
            return True
        except Exception:
            return False

    def list_keys(self, prefix: str) -> list[str]:
        return [key for key, _ in self.list_entries(prefix)]

    def list_entries(self, prefix: str) -> list[tuple[str, int]]:
        full_prefix = self._full_key(prefix).rstrip("/") + "/"
        paginator = self._client.get_paginator("list_objects_v2")
        entries: list[tuple[str, int]] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=full_prefix):
            for item in page.get("Contents", []):
                raw = item["Key"]
                if self.prefix:
                    raw = raw[len(self.prefix) + 1:]
                entries.append((raw, int(item.get("Size", 0))))
        return entries

    def get_bytes(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self.bucket, Key=self._full_key(key))
        return response["Body"].read()

    def put_bytes(self, key: str, data: bytes) -> None:
        self._client.put_object(Bucket=self.bucket, Key=self._full_key(key), Body=data)

    def delete_keys(self, keys: list[str]) -> None:
        if not keys:
            return
        full_keys = [{"Key": self._full_key(key)} for key in keys]
        for start in range(0, len(full_keys), 1000):
            self._client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": full_keys[start:start + 1000], "Quiet": True},
            )

    def delete_prefix(self, prefix: str) -> None:
        keys = self.list_keys(prefix)
        self.delete_keys(keys)


def download_prefix(store: ObjectStore, prefix: str, destination: Path) -> None:
    """Download an object-store prefix into a local directory."""
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    for key in store.list_keys(prefix):
        relative = key[len(prefix.rstrip("/") + "/"):] if prefix else key
        if not relative:
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(store.get_bytes(key))


def upload_tree(store: ObjectStore, source: Path, prefix: str) -> None:
    """Upload a local directory tree to the object store prefix."""
    if not source.exists():
        return
    base = prefix.rstrip("/")
    for path in source.rglob("*"):
        if ".git" in path.parts:
            continue
        if not path.is_file():
            continue
        rel = path.relative_to(source).as_posix()
        key = f"{base}/{rel}" if base else rel
        store.put_bytes(key, path.read_bytes())
