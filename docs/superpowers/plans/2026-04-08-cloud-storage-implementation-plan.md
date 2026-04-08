# Cloud Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 支持通过配置切换到 COS（腾讯云对象存储），存储路径前缀 `mclaw/`，使用 boto3 S3 兼容 API。

**Architecture:** 新增 `CloudStorage` 接口 + `S3CompatibleStorage` 实现，通过 `StorageBackendFactory` 根据配置切换本地/COS 存储。改动覆盖 `MemoryStore`、`SessionManager`、工具结果持久化、`GitStore` 云端禁用。

**Tech Stack:** `boto3`、`moto`（测试 mock）、Pydantic 配置扩展。

---

## 文件结构

**新建：**
- `nanobot/providers/cloud_storage.py` — `CloudStorage` 接口、`S3CompatibleStorage` 实现、`StorageBackendFactory`
- `tests/providers/test_cloud_storage.py` — 接口和实现测试（moto mock）

**修改：**
- `nanobot/config/schema.py` — 新增 `CloudStorageConfig` Pydantic 模型，字段：`provider`、`endpoint_url`、`bucket`、`region`、`secret_id`、`secret_key`、`prefix`
- `nanobot/agent/memory.py` — `MemoryStore` 注入 `CloudStorage`，替换所有 `Path.read_text()`/`Path.write_text()` 为 `storage.read()`/`storage.write()`
- `nanobot/session/manager.py` — `SessionManager` 注入 `CloudStorage`，替换 session 文件 I/O
- `nanobot/utils/helpers.py` — `maybe_persist_tool_result` 和 `load_tool_result` 使用 `CloudStorage`
- `nanobot/utils/gitstore.py` — `GitStore.is_available()` 云端模式返回 `False`
- `nanobot/config/loader.py` — `load_config` 后调用 `resolve_config_env_vars` 解析 `${ENV_VAR}` 占位符（目前 `resolve_config_env_vars` 已是独立函数，需确保在 `load_config` 之后调用）
- `pyproject.toml` — 新增 `boto3` 依赖；`dev` 新增 `moto`

---

## Task 1: 添加 CloudStorageConfig 到 schema.py

**Files:**
- Modify: `nanobot/config/schema.py`

- [ ] **Step 1: 添加 CloudStorageConfig 类**

在 `schema.py` 末尾（在 `Config` 类之前）添加：

```python
class CloudStorageConfig(Base):
    """Cloud storage configuration for COS/S3-compatible backends."""

    provider: str = "cos"  # "cos" or "s3"
    endpoint_url: str = ""
    bucket: str = ""
    region: str = ""  # 保留字段，实际 endpoint_url 固定值
    secret_id: str = ""
    secret_key: str = ""
    prefix: str = "mclaw/"  # 所有文件的公共前缀
```

- [ ] **Step 2: 在 Config 类中添加 cloud_storage 字段**

在 `Config` 类 `agents` 字段后添加：

```python
cloud_storage: CloudStorageConfig | None = None
```

- [ ] **Step 3: 运行 lint 检查**

```bash
cd D:/0workplace/nanobot && ruff check nanobot/config/schema.py
```

Expected: 无错误

- [ ] **Step 4: Commit**

```bash
git add nanobot/config/schema.py && git commit -m "feat(config): add CloudStorageConfig model"
```

---

## Task 2: 添加 boto3 和 moto 依赖

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: 添加依赖**

在 `dependencies` 数组中添加（位置任意，建议在 `dulwich` 之后）：

```toml
"boto3>=1.34.0,<2.0.0",
```

在 `dev` 数组中添加：

```toml
"moto>=5.0.0,<6.0.0",
```

- [ ] **Step 2: Commit**

```bash
git add pyproject.toml && git commit -m "feat: add boto3 and moto dependencies"
```

---

## Task 3: 实现 CloudStorage 接口和 S3CompatibleStorage

**Files:**
- Create: `nanobot/providers/cloud_storage.py`

- [ ] **Step 1: 创建 cloud_storage.py 文件**

```python
"""Cloud storage: interface + S3-compatible implementation."""

from __future__ import annotations

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
        from pathlib import Path
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
```

- [ ] **Step 2: 运行 lint 检查**

```bash
cd D:/0workplace/nanobot && ruff check nanobot/providers/cloud_storage.py
```

Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add nanobot/providers/cloud_storage.py && git commit -m "feat(cloud): add CloudStorage interface and S3CompatibleStorage implementation"
```

---

## Task 4: 为 CloudStorage 写单元测试

**Files:**
- Create: `tests/providers/test_cloud_storage.py`

- [ ] **Step 1: 编写 S3CompatibleStorage read/write/list/exists/delete 测试**

```python
"""Tests for S3CompatibleStorage using moto mock."""

import pytest
from moto import mock_aws

from nanobot.config.schema import CloudStorageConfig
from nanobot.providers.cloud_storage import S3CompatibleStorage


@pytest.fixture
def storage():
    config = CloudStorageConfig(
        provider="cos",
        endpoint_url="https://cos.ap-beijing.myqcloud.com",
        bucket="test-bucket",
        region="ap-beijing",
        secret_id="test-id",
        secret_key="test-key",
        prefix="mclaw/",
    )
    with mock_aws():
        yield S3CompatibleStorage(config)


def test_write_and_read(storage):
    storage.write("test/file.txt", b"hello world")
    assert storage.read("test/file.txt") == b"hello world"


def test_read_nonexistent_raises(storage):
    import pytest
    with pytest.raises(FileNotFoundError):
        storage.read("nonexistent/file.txt")


def test_exists(storage):
    assert storage.exists("test/file.txt") is False
    storage.write("test/file.txt", b"data")
    assert storage.exists("test/file.txt") is True


def test_list(storage):
    storage.write("dir/file1.txt", b"data1")
    storage.write("dir/file2.txt", b"data2")
    storage.write("other/file3.txt", b"data3")
    keys = sorted(storage.list("dir/"))
    assert keys == ["file1.txt", "file2.txt"]


def test_delete(storage):
    storage.write("to_delete.txt", b"data")
    assert storage.exists("to_delete.txt") is True
    storage.delete("to_delete.txt")
    assert storage.exists("to_delete.txt") is False


def test_prefix_applied(storage):
    """Verify prefix 'mclaw/' is prepended to all keys."""
    storage.write("memory/history.jsonl", b"[]")
    # 实际 key 应该带 prefix
    import boto3
    client = boto3.client(
        "s3",
        endpoint_url="https://cos.ap-beijing.myqcloud.com",
        aws_access_key_id="test-id",
        aws_secret_access_key="test-key",
    )
    # moto 下 bucket 需要先 create
    client.create_bucket(Bucket="test-bucket")
    storage.write("memory/history.jsonl", b"[]")
    response = client.list_objects_v2(Bucket="test-bucket")
    keys = [obj["Key"] for obj in response.get("Contents", [])]
    assert any(k == "mclaw/memory/history.jsonl" for k in keys)
```

- [ ] **Step 2: 运行测试（需要先 create bucket）**

先在 `test_write_and_read` 里加上 `client.create_bucket(Bucket="test-bucket")`：

```python
def test_write_and_read(storage):
    import boto3
    client = boto3.client("s3", endpoint_url="https://cos.ap-beijing.myqcloud.com",
                          aws_access_key_id="test-id", aws_secret_access_key="test-key")
    client.create_bucket(Bucket="test-bucket")
    storage.write("test/file.txt", b"hello world")
    assert storage.read("test/file.txt") == b"hello world"
```

运行：

```bash
cd D:/0workplace/nanobot && pytest tests/providers/test_cloud_storage.py -v
```

Expected: PASS（所有测试通过）

- [ ] **Step 3: Commit**

```bash
git add tests/providers/test_cloud_storage.py && git commit -m "test(cloud): add S3CompatibleStorage unit tests with moto"
```

---

## Task 5: 改造 MemoryStore 使用 CloudStorage

**Files:**
- Modify: `nanobot/agent/memory.py`

- [ ] **Step 1: 修改 MemoryStore.__init__ 接受 CloudStorage**

```python
from __future__ import annotations

import asyncio
import json
import re
import weakref
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from loguru import logger

from nanobot.utils.prompt_templates import render_template
from nanobot.utils.helpers import ensure_dir, estimate_message_tokens, estimate_prompt_tokens_chain, strip_think
from nanobot.providers.cloud_storage import CloudStorage, create_storage

from nanobot.agent.runner import AgentRunSpec, AgentRunner
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.utils.gitstore import GitStore

if TYPE_CHECKING:
    from nanobot.providers.base import LLMProvider
    from nanobot.session.manager import Session, SessionManager
    from nanobot.config.schema import CloudStorageConfig


class MemoryStore:
    """Pure file I/O for memory files via CloudStorage."""

    _DEFAULT_MAX_HISTORY = 1000
    _LEGACY_ENTRY_START_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2}[^\]]*)\]\s*")
    _LEGACY_TIMESTAMP_RE = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\]\s*")
    _LEGACY_RAW_MESSAGE_RE = re.compile(
        r"^\[\d{4}-\d{2}-\d{2}[^\]]*\]\s+[A-Z][A-Z0-9_]*(?:\s+\[tools:\s*[^\]]+\])?:"
    )

    def __init__(
        self,
        workspace: Path,
        cloud_config: "CloudStorageConfig | None" = None,
        max_history_entries: int = _DEFAULT_MAX_HISTORY,
    ):
        self.workspace = workspace
        self._storage = create_storage(cloud_config, workspace)
        self.max_history_entries = max_history_entries
        self._git = GitStore(workspace, tracked_files=[
            "SOUL.md", "USER.md", "memory/MEMORY.md",
        ])
        # SOUL.md, USER.md, memory/ 文件首次访问时通过 storage 读写
        self._maybe_migrate_legacy_history()
```

- [ ] **Step 2: 添加 storage-based 文件读写方法**

在 `MemoryStore` 类中添加：

```python
    def _read_text(self, key: str) -> str:
        try:
            return self._storage.read(key).decode("utf-8")
        except FileNotFoundError:
            return ""

    def _write_text(self, key: str, content: str) -> None:
        self._storage.write(key, content.encode("utf-8"))

    def _read_bytes(self, key: str) -> bytes:
        return self._storage.read(key)

    def _write_bytes(self, key: str, data: bytes) -> None:
        self._storage.write(key, data)

    def _exists(self, key: str) -> bool:
        return self._storage.exists(key)

    def _list_keys(self, prefix: str) -> list[str]:
        return self._storage.list(prefix)

    def _delete(self, key: str) -> None:
        self._storage.delete(key)
```

- [ ] **Step 3: 替换所有文件路径属性为 key-based**

将属性：
```python
self.memory_dir = ensure_dir(workspace / "memory")
self.memory_file = self.memory_dir / "MEMORY.md"
self.history_file = self.memory_dir / "history.jsonl"
self.legacy_history_file = self.memory_dir / "HISTORY.md"
self.soul_file = workspace / "SOUL.md"
self.user_file = workspace / "USER.md"
self._cursor_file = self.memory_dir / ".cursor"
self._dream_cursor_file = self.memory_dir / ".dream_cursor"
```

替换为 key 属性（不再拼接本地路径）：

```python
    # CloudStorage keys
    @property
    def _memory_dir_key(self) -> str:
        return "memory"

    @property
    def _memory_file_key(self) -> str:
        return "memory/MEMORY.md"

    @property
    def _history_file_key(self) -> str:
        return "memory/history.jsonl"

    @property
    def _legacy_history_file_key(self) -> str:
        return "memory/HISTORY.md"

    @property
    def _soul_file_key(self) -> str:
        return "SOUL.md"

    @property
    def _user_file_key(self) -> str:
        return "USER.md"

    @property
    def _cursor_file_key(self) -> str:
        return "memory/.cursor"

    @property
    def _dream_cursor_file_key(self) -> str:
        return "memory/.dream_cursor"
```

- [ ] **Step 4: 替换所有 `Path.read_text()` / `Path.write_text()` 调用**

将 `MemoryStore` 中所有对以下本地路径的读写调用改为 `_read_text` / `_write_text`：

1. `self.memory_file` → `self._memory_file_key`，`read_file(self.memory_file)` → `_read_text(self._memory_file_key)`
2. `self.history_file` → `self._history_file_key`
3. `self.legacy_history_file` → `self._legacy_history_file_key`
4. `self.soul_file` → `self._soul_file_key`
5. `self.user_file` → `self._user_file_key`
6. `self._cursor_file` → `self._cursor_file_key`
7. `self._dream_cursor_file` → `self._dream_cursor_file_key`

**重要：** 逐个方法替换，不要一次性全部替换。先读懂每个方法的逻辑，再改对应调用。

需要替换的具体模式：
- `path.read_text(encoding="utf-8")` → `_read_text(str(path))` 或直接用 key
- `path.write_text(str_val, encoding="utf-8")` → `_write_text(key, str_val)`
- `path.exists()` → `_exists(key)`
- `path.stat().st_size > 0` → `_exists(key)` + try/except
- `path.replace(backup_path)` → 改为 `_read_text` → `_write_text` → `_delete`
- `Path(path)` 构造 → 用 key string

- [ ] **Step 5: 运行 lint 检查**

```bash
cd D:/0workplace/nanobot && ruff check nanobot/agent/memory.py
```

Expected: 无错误

- [ ] **Step 6: 运行 MemoryStore 相关测试**

```bash
cd D:/0workplace/nanobot && pytest tests/agent/test_memory*.py -v
```

Expected: 原有测试通过（本地模式下行为不变）

- [ ] **Step 7: Commit**

```bash
git add nanobot/agent/memory.py && git commit -m "refactor(memory): use CloudStorage for all file I/O"
```

---

## Task 6: 改造 SessionManager 使用 CloudStorage

**Files:**
- Modify: `nanobot/session/manager.py`

- [ ] **Step 1: 修改 SessionManager.__init__ 接受 CloudStorage**

```python
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.config.paths import get_legacy_sessions_dir
from nanobot.utils.helpers import ensure_dir, find_legal_message_start, safe_filename
from nanobot.providers.cloud_storage import CloudStorage, create_storage

if TYPE_CHECKING:
    from nanobot.config.schema import CloudStorageConfig


class SessionManager:
    """
    Manages conversation sessions via CloudStorage.
    """

    def __init__(
        self,
        workspace: Path,
        cloud_config: "CloudStorageConfig | None" = None,
    ):
        self.workspace = workspace
        self._storage = create_storage(cloud_config, workspace)
        self._legacy_sessions_dir = get_legacy_sessions_dir()
        self._cache: dict[str, Session] = {}
```

- [ ] **Step 2: 添加 storage-based 会话文件读写方法**

在 `SessionManager` 中添加私有方法：

```python
    def _get_session_key(self, key: str) -> str:
        safe_key = safe_filename(key.replace(":", "_"))
        return f"sessions/{safe_key}.jsonl"

    def _read_session_bytes(self, key: str) -> bytes | None:
        session_key = self._get_session_key(key)
        try:
            return self._storage.read(session_key)
        except FileNotFoundError:
            return None

    def _write_session_bytes(self, key: str, data: bytes) -> None:
        session_key = self._get_session_key(key)
        self._storage.write(session_key, data)
```

- [ ] **Step 3: 替换 _load 方法**

将 `_load` 中的 `path.exists()` / `path.read_text()` 改为 storage 方法：
- `self._get_session_path(key)` → session_key (string)
- `path.exists()` → `_read_session_bytes(key)` is not None
- `json.loads(path.read_text())` → `json.loads(_read_session_bytes(key).decode())`

迁移逻辑（`shutil.move`）保留，但目标路径改为 storage：
- `shutil.move(str(legacy_path), str(path))` → 改为从 legacy 读，写入新 storage key，再删除 legacy

- [ ] **Step 4: 替换 save 方法**

`SessionManager.save()` 中将 `path.write_text(json.dumps(...), ...)` 改为 `_write_session_bytes(key, json.dumps(...).encode())`。

- [ ] **Step 5: 替换 _get_session_path 相关引用**

`__init__` 中不再需要 `self.sessions_dir = ensure_dir(...)`（sessions_dir 本地路径不再需要），删除此行。

- [ ] **Step 6: 运行 lint 检查**

```bash
cd D:/0workplace/nanobot && ruff check nanobot/session/manager.py
```

Expected: 无错误

- [ ] **Step 7: 运行 SessionManager 相关测试**

```bash
cd D:/0workplace/nanobot && pytest tests/session/ -v
```

Expected: 原有测试通过

- [ ] **Step 8: Commit**

```bash
git add nanobot/session/manager.py && git commit -m "refactor(session): use CloudStorage for session persistence"
```

---

## Task 7: 改造工具结果持久化使用 CloudStorage

**Files:**
- Modify: `nanobot/utils/helpers.py`

- [ ] **Step 1: 找到 `_TOOL_RESULTS_DIR` 使用位置并改为 CloudStorage**

`maybe_persist_tool_result` 函数（大约 line 187）中：
- `workspace / _TOOL_RESULTS_DIR` → 改为拼接 COS key: `f"{_TOOL_RESULTS_DIR}/{session_key}/{filename}"`
- 写文件操作改为 `storage.write(key, data)`

由于 `maybe_persist_tool_result` 接收的是 `workspace: Path | None`，需要从调用方传入 storage 或通过全局方式获取。建议：

在 `helpers.py` 添加一个 module-level `CloudStorage` 实例，在 nanobot 初始化时注入：

```python
# nanobot/utils/helpers.py 顶部添加
_storage: "CloudStorage | None = None"

def set_storage(storage: "CloudStorage | None") -> None:
    """Called during nanobot init to provide CloudStorage for helpers."""
    global _storage
    _storage = storage

def get_storage() -> "CloudStorage | None":
    return _storage
```

`maybe_persist_tool_result` 中：
- 当 `workspace is not None and _storage is not None` 时，用 storage
- 否则保持现有本地文件行为（向后兼容本地模式）

写入 COS 时，key 格式为：`{_TOOL_RESULTS_DIR}/{bucket}/{filename}`。

同样改造 `load_tool_result` 函数（如果存在的话）。

- [ ] **Step 2: 运行 lint 检查**

```bash
cd D:/0workplace/nanobot && ruff check nanobot/utils/helpers.py
```

Expected: 无错误

- [ ] **Step 3: Commit**

```bash
git add nanobot/utils/helpers.py && git commit -m "refactor(helpers): use CloudStorage for tool result persistence"
```

---

## Task 8: 禁用 GitStore 云端模式

**Files:**
- Modify: `nanobot/utils/gitstore.py`

- [ ] **Step 1: 修改 GitStore 以支持云端禁用**

在 `GitStore.__init__` 中添加参数：

```python
def __init__(
    self,
    workspace: Path,
    tracked_files: list[str],
    enabled: bool = True,
):
    self._workspace = workspace
    self._tracked_files = tracked_files
    self._enabled = enabled
```

`is_available()` 方法：

```python
def is_available(self) -> bool:
    if not self._enabled:
        return False
    return (self._workspace / ".git").is_dir()
```

- [ ] **Step 2: 在 MemoryStore 构造 GitStore 时传入 enabled**

MemoryStore 中，cloud_config 存在时 `enabled=False`：

```python
self._git = GitStore(
    workspace,
    tracked_files=["SOUL.md", "USER.md", "memory/MEMORY.md"],
    enabled=(cloud_config is None),  # 云端模式禁用 GitStore
)
```

- [ ] **Step 3: 运行 lint 检查**

```bash
cd D:/0workplace/nanobot && ruff check nanobot/utils/gitstore.py nanobot/agent/memory.py
```

Expected: 无错误

- [ ] **Step 4: Commit**

```bash
git add nanobot/utils/gitstore.py nanobot/agent/memory.py && git commit -m "feat(gitstore): add enabled flag, disable in cloud mode"
```

---

## Task 9: 改造 sync_workspace_templates 使用 CloudStorage

**Files:**
- Modify: `nanobot/utils/helpers.py` 中 `sync_workspace_templates` 函数

- [ ] **Step 1: 改造 sync_workspace_templates**

`sync_workspace_templates` 当前将模板文件从包内复制到 workspace。在 cloud 模式下应改为通过 storage 写入。

函数签名不变（仍然接收 `workspace: Path`），内部判断：
- 如果 `_storage is not None` → 用 `_storage.write(key, content_bytes)`
- 否则保持现有本地文件行为

- [ ] **Step 2: 运行 lint 检查**

```bash
cd D:/0workplace/nanobot && ruff check nanobot/utils/helpers.py
```

- [ ] **Step 3: Commit**

```bash
git add nanobot/utils/helpers.py && git commit -m "refactor(helpers): sync_workspace_templates uses CloudStorage when available"
```

---

## Task 10: 端到端集成验证

- [ ] **Step 1: 创建 cloud storage 模式的 config.json 示例**

```bash
cat > /tmp/cloud_config_example.json << 'EOF'
{
  "workspace": "/tmp/nanobot-workspace",
  "cloud_storage": {
    "provider": "cos",
    "endpoint_url": "https://cos.ap-beijing.myqcloud.com",
    "bucket": "example-bucket",
    "region": "ap-beijing",
    "secret_id": "${COS_SECRET_ID}",
    "secret_key": "${COS_SECRET_KEY}",
    "prefix": "mclaw/"
  }
}
```

- [ ] **Step 2: 用 moto 模拟 COS，验证 MemoryStore 完整流程**

```python
# tests/integration/test_cloud_storage_integration.py
import pytest
from moto import mock_aws

from nanobot.config.schema import CloudStorageConfig, AgentDefaults, AgentsConfig
from nanobot.providers.cloud_storage import S3CompatibleStorage, create_storage
from nanobot.agent.memory import MemoryStore


@mock_aws
def test_memory_store_full_cycle():
    import boto3
    client = boto3.client("s3", endpoint_url="https://cos.example.com",
                          aws_access_key_id="x", aws_secret_access_key="x")
    client.create_bucket(Bucket="test-bucket")

    config = CloudStorageConfig(
        provider="cos",
        endpoint_url="https://cos.example.com",
        bucket="test-bucket",
        region="ap-beijing",
        secret_id="x",
        secret_key="x",
        prefix="mclaw/",
    )
    from pathlib import Path
    store = MemoryStore(Path("/tmp/workspace"), cloud_config=config)
    store.write_memory_file("test content")
    assert store.read_memory_file() == "test content"
    assert store.exists("memory/MEMORY.md") is True
```

- [ ] **Step 3: 运行全部测试**

```bash
cd D:/0workplace/nanobot && pytest tests/ -v --tb=short
```

Expected: 全部通过

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_cloud_storage_integration.py 2>/dev/null || true
git commit -m "test: add cloud storage integration test" 2>/dev/null || true
```

---

## Task 11: 更新 CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 在 Development Commands 部分添加 cloud storage 测试说明**

在 "Run all tests" 之后添加：

```markdown
## Cloud Storage (COS)

When `cloud_storage` is configured in `config.json`, nanobot uses COS (Tencent Cloud Object Storage) via S3-compatible API instead of local disk.

Config example:
```json
{
  "cloud_storage": {
    "provider": "cos",
    "endpoint_url": "https://cos.ap-beijing.myqcloud.com",
    "bucket": "your-bucket",
    "region": "ap-beijing",
    "secret_id": "${COS_SECRET_ID}",
    "secret_key": "${COS_SECRET_KEY}",
    "prefix": "mclaw/"
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md && git commit -m "docs: add cloud storage configuration to CLAUDE.md"
```
