# Multi-User Workspace Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标:** 实现多用户 workspace 隔离，每个用户通过 `sender_id` 区分，workspace 路径结构为 `~/.nanobot/workspaces/{sender_id}/`。

**架构:** 使用 `contextvars.ContextVar` 在协程栈中传递当前用户 ID。`_dispatch` 在处理消息前设置 context，文件系统工具和存储层从 context 读取 userId 注入路径前缀。

**技术栈:** Python contextvars, pathlib, CloudStorage (S3-compatible)

---

## 文件地图

```
nanobot/utils/user_context.py          (新建) — ContextVar 管理 current_user_id
nanobot/agent/loop.py                  (修改) — _dispatch 设置/清理 user context
nanobot/agent/tools/filesystem.py      (修改) — _FsTool 路径解析注入 userId 前缀
nanobot/utils/helpers.py               (修改) — maybe_persist_tool_result 支持 userId
nanobot/agent/context.py              (修改) — ContextBuilder 使用 user-scoped workspace
nanobot/session/manager.py            (修改) — SessionManager 使用 user-scoped workspace
tests/agent/test_user_context.py      (新建) — ContextVar 单元测试
tests/agent/test_loop_workspace.py    (新建) — workspace 隔离集成测试
```

---

## Task 1: 创建 user_context.py（ContextVar 管理）

**文件:**
- 新建: `nanobot/utils/user_context.py`

- [ ] **Step 1: 创建 user_context.py**

```python
"""User context — carries the current user ID through the async call stack."""

from contextvars import ContextVar

_current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)


def set_current_user_id(user_id: str | None) -> None:
    """Set the current user ID for this async context."""
    _current_user_id.set(user_id)


def get_current_user_id() -> str | None:
    """Get the current user ID for this async context, or None if not set."""
    return _current_user_id.get()


def clear_current_user_id() -> None:
    """Clear the current user ID (used in finally blocks)."""
    _current_user_id.set(None)
```

- [ ] **Step 2: 验证导入正常**

Run: `python -c "from nanobot.utils.user_context import get_current_user_id, set_current_user_id; print('OK')"`
Expected: `OK`

- [ ] **Step 3: 编写单元测试**

新建 `tests/agent/test_user_context.py`:

```python
"""Tests for user_context ContextVar."""

import pytest
from nanobot.utils.user_context import (
    get_current_user_id,
    set_current_user_id,
    clear_current_user_id,
)


def test_default_is_none():
    """No user set by default."""
    clear_current_user_id()
    assert get_current_user_id() is None


def test_set_and_get():
    """Can set and retrieve user ID."""
    set_current_user_id("alice")
    try:
        assert get_current_user_id() == "alice"
    finally:
        clear_current_user_id()


def test_clear_resets_to_none():
    """Clearing resets to None."""
    set_current_user_id("alice")
    clear_current_user_id()
    assert get_current_user_id() is None


def test_isolation_across_contexts():
    """Setting user in one context does not affect another."""
    import contextvars

    results: list[str | None] = []

    async def inner(ctx: contextvars.Context):
        def get_in_ctx():
            return contextvars.copy_context().run(get_current_user_id)

        results.append(get_in_ctx())

    # Run in separate contexts to verify isolation
    import asyncio
    async def main():
        set_current_user_id("alice")
        try:
            results.append(get_current_user_id())
            # Create new task with fresh context
            task = asyncio.create_task(inner(contextvars.copy_context()))
            await task
        finally:
            clear_current_user_id()

    asyncio.run(main())
    # Main context should have alice, inner (copied) context should NOT
    assert results[0] == "alice"
    assert results[1] is None  # copied context doesn't have the token
```

- [ ] **Step 4: 运行测试**

Run: `pytest tests/agent/test_user_context.py -v`

- [ ] **Step 5: 提交**

```bash
git add nanobot/utils/user_context.py tests/agent/test_user_context.py
git commit -m "feat(utils): add user_context ContextVar for current user ID"
```

---

## Task 2: 修改 loop.py — _dispatch 设置/清理 user context

**文件:**
- 修改: `nanobot/agent/loop.py:452-520`

- [ ] **Step 1: 添加 import**

在 `nanobot/agent/loop.py` 顶部添加：

```python
from nanobot.utils.user_context import set_current_user_id, clear_current_user_id
```

- [ ] **Step 2: 修改 _dispatch 方法**

在 `_dispatch` 方法的锁获取后、`_process_message` 调用前添加 context 设置。

找到 `_dispatch` 方法中 `async with lock, gate:` 块，在方法开始（`try` 块最开头）添加：

```python
async def _dispatch(self, msg: InboundMessage) -> None:
    """Process a message: per-session serial, cross-session concurrent."""
    lock = self._session_locks.setdefault(msg.session_key, asyncio.Lock())
    gate = self._concurrency_gate or nullcontext()
    async with lock, gate:
        set_current_user_id(msg.sender_id)
        try:
            # ... 原有 try 块内容 ...
        finally:
            clear_current_user_id()
```

具体修改：在 `try:` 之后立即添加 `set_current_user_id(msg.sender_id)`，在 `finally:` 块中添加 `clear_current_user_id()`。

- [ ] **Step 3: 运行现有测试验证无回归**

Run: `pytest tests/agent/test_loop_consolidation_tokens.py tests/agent/test_loop_save_turn.py -v`
Expected: 全部 PASS

- [ ] **Step 4: 提交**

```bash
git add nanobot/agent/loop.py
git commit -m "feat(agent): set/clear user context in _dispatch for workspace isolation"
```

---

## Task 3: 修改 filesystem.py — 路径解析注入 userId 前缀

**文件:**
- 修改: `nanobot/agent/tools/filesystem.py`

- [ ] **Step 1: 添加 import**

在 `nanobot/agent/tools/filesystem.py` 顶部添加：

```python
from nanobot.utils.user_context import get_current_user_id
```

- [ ] **Step 2: 修改 _FsTool._resolve 方法**

在 `_FsTool` 类的 `_resolve` 方法开头，添加 userId 前缀注入：

```python
def _resolve(self, path: str) -> Path:
    # Inject userId prefix for relative paths when user context is set
    user_id = get_current_user_id()
    if user_id and not Path(path).is_absolute():
        path = f"workspaces/{user_id}/{path}"
    return _resolve_path(path, self._workspace, self._allowed_dir, self._extra_allowed_dirs)
```

- [ ] **Step 3: 修改 _FsTool._storage_key 方法**

同样在 `_storage_key` 方法中添加 userId 前缀：

```python
def _storage_key(self, path: str) -> str | None:
    """Return storage key if path is under workspace, None otherwise."""
    if self._workspace is None:
        return None
    user_id = get_current_user_id()
    if user_id:
        # Prepend user-specific prefix for cloud storage keys
        base_key = f"workspaces/{user_id}/"
    else:
        base_key = ""
    try:
        resolved = self._resolve(path).resolve()
        rel = resolved.relative_to(self._workspace.resolve())
        return base_key + str(rel).replace("\\", "/")
    except ValueError:
        return None
```

- [ ] **Step 4: 运行现有 filesystem 测试**

Run: `pytest tests/tools/test_filesystem_tools.py -v`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add nanobot/agent/tools/filesystem.py
git commit -m "feat(filesystem): inject userId prefix into paths for workspace isolation"
```

---

## Task 4: 修改 helpers.py — maybe_persist_tool_result 支持 userId

**文件:**
- 修改: `nanobot/utils/helpers.py`

- [ ] **Step 1: 添加 import**

在 `nanobot/utils/helpers.py` 导入区域添加：

```python
from nanobot.utils.user_context import get_current_user_id
```

- [ ] **Step 2: 修改 maybe_persist_tool_result 函数**

需要修改本地文件 fallback 逻辑，因为 `_storage_key` 返回的相对路径已包含 `workspaces/{user_id}/` 前缀（由 Task 3 的 `_FsTool._storage_key` 处理），不能直接作为 `workspace` 的相对子路径。

在 `maybe_persist_tool_result` 函数中找到本地文件 fallback 块（约第 248 行）：

找到：
```python
else:
    # Local file fallback
    root = ensure_dir(workspace / _TOOL_RESULTS_DIR)
    bucket = ensure_dir(root / safe_filename(session_key or "default"))
```

改为：
```python
else:
    # Local file fallback
    # storage_key may be a user-scoped relative path like "workspaces/{user_id}/.tool-results/..."
    # We need to write to workspace / storage_key (not workspace / _TOOL_RESULTS_DIR / ...)
    key = storage_key  # already includes user prefix from _FsTool._storage_key
    local_path = workspace / key
    bucket = ensure_dir(local_path.parent)
```

- [ ] **Step 3: 运行测试验证**

Run: `pytest tests/ -v -k "tool_result or persist" --no-header -q`
Expected: 全部 PASS

- [ ] **Step 4: 提交**

```bash
git add nanobot/utils/helpers.py
git commit -m "feat(storage): inject userId prefix into tool result storage keys"
```

---

## Task 5: 修改 context.py — MemoryStore 使用 user-scoped workspace

**文件:**
- 修改: `nanobot/agent/context.py`

- [ ] **Step 1: 添加 import**

在 `nanobot/agent/context.py` 顶部添加：

```python
from nanobot.utils.user_context import get_current_user_id
```

- [ ] **Step 2: 添加 _get_user_scoped_workspace 方法**

在 `ContextBuilder` 类中添加：

```python
def _get_user_scoped_workspace(self) -> Path:
    """Return workspace path scoped to current user, or self.workspace if no user set."""
    user_id = get_current_user_id()
    if not user_id:
        return self.workspace
    return self.workspace / "workspaces" / user_id
```

- [ ] **Step 3: 修改 memory 和 skills 的 workspace 引用**

在 `__init__` 中，memory 和 skills 使用 user-scoped workspace 初始化：

找到：
```python
self.memory = MemoryStore(workspace, cloud_config=cloud_config)
self.skills = SkillsLoader(workspace)
```

改为：
```python
scoped_workspace = self._get_user_scoped_workspace()
self.memory = MemoryStore(scoped_workspace, cloud_config=cloud_config)
self.skills = SkillsLoader(scoped_workspace)
```

- [ ] **Step 4: 运行测试验证**

Run: `pytest tests/agent/ -v --no-header -q`
Expected: 全部 PASS

- [ ] **Step 5: 提交**

```bash
git add nanobot/agent/context.py
git commit -m "feat(context): use user-scoped workspace for memory and skills"
```

---

## Task 6: 修改 session/manager.py — SessionManager workspace 隔离

**文件:**
- 修改: `nanobot/session/manager.py`

- [ ] **Step 1: 添加 import**

在 `nanobot/session/manager.py` 顶部添加：

```python
from nanobot.utils.user_context import get_current_user_id
```

- [ ] **Step 2: 修改 SessionManager.__init__ 保存 scoped workspace**

找到 `SessionManager.__init__`:

```python
def __init__(
    self,
    workspace: Path,
    cloud_config: "CloudStorageConfig | None" = None,
):
    self.workspace = workspace
    self._storage = create_storage(cloud_config, workspace)
```

改为：

```python
def __init__(
    self,
    workspace: Path,
    cloud_config: "CloudStorageConfig | None" = None,
):
    self._base_workspace = workspace
    user_id = get_current_user_id()
    self.workspace = workspace / "workspaces" / user_id if user_id else workspace
    self._storage = create_storage(cloud_config, self.workspace)
```

- [ ] **Step 3: 运行测试验证**

Run: `pytest tests/ -v --no-header -q 2>&1 | tail -20`
Expected: 全部 PASS

- [ ] **Step 4: 提交**

```bash
git add nanobot/session/manager.py
git commit -m "feat(session): use user-scoped workspace for session storage"
```

---

## Task 7: 集成测试

**文件:**
- 新建: `tests/agent/test_loop_workspace.py`

- [ ] **Step 1: 编写 workspace 隔离集成测试**

```python
"""Integration tests for multi-user workspace isolation."""

import pytest
from pathlib import Path
from unittest.mock import patch

from nanobot.agent.loop import AgentLoop
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus import InMemoryBus
from nanobot.config.schema import Config
from nanobot.providers.base import LLMProvider, AgentMessage, ToolCall
from nanobot.utils.user_context import set_current_user_id, clear_current_user_id, get_current_user_id
from nanobot.bus.events import InboundMessage


class DummyProvider(LLMProvider):
    """Minimal provider for testing."""

    def __init__(self):
        pass

    @property
    def model_name(self) -> str:
        return "test"

    @property
    def provider_name(self) -> str:
        return "test"

    async def complete(
        self, messages, system_prompt=None, tools=None, tool_choice=None, **kwargs
    ) -> AgentMessage:
        return AgentMessage(role="assistant", content="ok")

    async def complete_stream(self, *args, **kwargs):
        yield AgentMessage(role="assistant", content="ok")


@pytest.fixture
def workspace(tmp_path):
    """Create a temp workspace."""
    return tmp_path


@pytest.fixture
def config(workspace):
    """Minimal config."""
    cfg = Config.model_validate({
        "providers": {"test": {"provider": "test"}},
        "workspace": str(workspace),
    })
    return cfg


async def test_user_context_set_in_dispatch(config, workspace):
    """Verify user context is set when processing a message."""
    seen_user_ids = []

    original_dispatch = AgentLoop._dispatch

    async def patched_dispatch(self, msg):
        seen_user_ids.append(get_current_user_id())
        return await original_dispatch(self, msg)

    bus = InMemoryBus()
    loop = AgentLoop(bus, DummyProvider(), config)
    loop._workspace = workspace

    with patch.object(AgentLoop, "_dispatch', patched_dispatch):
        await bus.publish_inbound(InboundMessage(
            channel="test",
            sender_id="alice",
            chat_id="chat1",
            content="hello",
        ))
        await asyncio.sleep(0.1)

    assert "alice" in seen_user_ids


async def test_filesystem_path_injects_user_prefix(tmp_path):
    """Verify filesystem tool resolves paths with user prefix."""
    from nanobot.agent.tools.filesystem import _FsTool

    workspace = tmp_path / "workspaces" / "alice"
    workspace.mkdir(parents=True)

    tool = _FsTool(workspace=workspace)

    set_current_user_id("alice")
    try:
        # A relative path should get workspaces/alice/ prepended
        resolved = tool._resolve("myfile.txt")
        assert "workspaces/alice" in str(resolved)
    finally:
        clear_current_user_id()


async def test_no_user_context_falls_back_to_workspace(tmp_path):
    """Without user context, paths resolve normally."""
    from nanobot.agent.tools.filesystem import _FsTool

    workspace = tmp_path
    tool = _FsTool(workspace=workspace)

    clear_current_user_id()
    resolved = tool._resolve("myfile.txt")
    assert "workspaces" not in str(resolved)
```

- [ ] **Step 2: 运行集成测试**

Run: `pytest tests/agent/test_loop_workspace.py -v`

- [ ] **Step 3: 提交**

```bash
git add tests/agent/test_loop_workspace.py
git commit -m "test: add workspace isolation integration tests"
```

---

## 需求覆盖检查

- [x] ContextVar 管理 user_id — Task 1
- [x] _dispatch 设置/清理 user context — Task 2
- [x] filesystem 路径注入 userId 前缀 — Task 3
- [x] maybe_persist_tool_result 支持 userId — Task 4
- [x] ContextBuilder memory/skills user-scoped — Task 5
- [x] SessionManager user-scoped workspace — Task 6
- [x] 集成测试 — Task 7
