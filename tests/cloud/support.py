from __future__ import annotations


class MemoryStore:
    """In-memory object store used by cloud tests."""

    def __init__(self):
        self.data: dict[str, bytes] = {}

    def exists(self, key: str) -> bool:
        return key in self.data

    def list_keys(self, prefix: str) -> list[str]:
        normalized = prefix.rstrip("/") + "/"
        return sorted(key for key in self.data if key.startswith(normalized))

    def get_bytes(self, key: str) -> bytes:
        return self.data[key]

    def put_bytes(self, key: str, data: bytes) -> None:
        self.data[key] = data

    def delete_prefix(self, prefix: str) -> None:
        normalized = prefix.rstrip("/") + "/"
        for key in [key for key in self.data if key.startswith(normalized)]:
            del self.data[key]
