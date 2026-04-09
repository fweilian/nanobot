# 用户 Workspace 初始化实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在用户首次通过 API（JWT 认证）登录后，自动初始化该用户的 workspace，支持本地和云端两种存储模式。

**Architecture:** JWT middleware 验签成功后，调用 `sync_workspace_templates` 初始化用户 workspace 目录。`sync_workspace_templates` 增加 `storage_prefix` 参数支持云存储 key 前缀。本地文件系统和云存储共用同一套幂等写入逻辑。

**Tech Stack:** aiohttp, PyJWT, CloudStorage (COS/S3 兼容), pathlib

---

## 文件地图

```
nanobot/api/middleware.py          (修改) — JWTAuthMiddleware 增加 workspace 初始化
nanobot/api/server.py             (修改) — create_app 恢复 workspace 参数
nanobot/utils/helpers.py           (修改) — sync_workspace_templates 增加 storage_prefix
nanobot/cli/commands.py            (修改) — serve 传入 workspace=agent_loop.workspace
tests/api/test_middleware.py       (修改) — 新增 workspace 初始化测试
tests/api/test_server.py           (修改) — 更新 create_app 测试
```

---

## Task 1: `sync_workspace_templates` 增加 `storage_prefix` 参数

**文件:**
- 修改: `nanobot/utils/helpers.py:479-530`

- [ ] **Step 1: 添加 `storage_prefix` 参数到函数签名**

将 `nanobot/utils/helpers.py:479` 从:
```python
def sync_workspace_templates(workspace: Path, silent: bool = False) -> list[str]:
```

改为:
```python
def sync_workspace_templates(workspace: Path, silent: bool = False, storage_prefix: str = "") -> list[str]:
```

- [ ] **Step 2: 修改 `_write` 调用，在 cloud storage key 前加上 `storage_prefix`**

将 `nanobot/utils/helpers.py:509` 从:
```python
_write(item, workspace / item.name, item.name)
```

改为:
```python
_write(item, workspace / item.name, f"{storage_prefix}{item.name}")
```

同样修改第 510 行:
```python
_write(tpl / "memory" / "MEMORY.md", workspace / "memory" / "MEMORY.md", f"{storage_prefix}memory/MEMORY.md")
```

第 511 行:
```python
_write(None, workspace / "memory" / "history.jsonl", f"{storage_prefix}memory/history.jsonl")
```

- [ ] **Step 3: 验证修改后导入正常**

运行: `python -c "from nanobot.utils.helpers import sync_workspace_templates; print('OK')"`
预期: `OK`

- [ ] **Step 4: 提交**

```bash
git add nanobot/utils/helpers.py
git commit -m "feat(helpers): add storage_prefix parameter to sync_workspace_templates"
```

---

## Task 2: `JWTAuthMiddleware` 增加 workspace 初始化

**文件:**
- 修改: `nanobot/api/middleware.py`

- [ ] **Step 1: 添加 import 和 `_ensure_user_workspace` 方法**

将 `nanobot/api/middleware.py` 顶部从:
```python
"""JWT 认证中间件，用于 aiohttp."""

from typing import Awaitable, Callable

import jwt
from aiohttp import web
```

改为:
```python
"""JWT 认证中间件，用于 aiohttp."""

import asyncio
from pathlib import Path
from typing import Awaitable, Callable

import jwt
from aiohttp import web
```

- [ ] **Step 2: 在 `__call__` 方法中，验签成功后调用 `_ensure_user_workspace`**

将 `nanobot/api/middleware.py:37-42` 从:
```python
user_id = payload.get("userId")
if not user_id:
    return _error(401, "Missing userId in token")

request["user_id"] = user_id
return await handler(request)
```

改为:
```python
user_id = payload.get("userId")
if not user_id:
    return _error(401, "Missing userId in token")

# 初始化用户 workspace（幂等操作，首次登录时触发）
await self._ensure_user_workspace(request, user_id)

request["user_id"] = user_id
return await handler(request)
```

- [ ] **Step 3: 添加 `_ensure_user_workspace` 方法**

在 `_error` 函数之后（第 49 行之后）添加:
```python
async def _ensure_user_workspace(self, request: web.Request, user_id: str) -> None:
    """确保用户 workspace 已初始化（幂等操作）."""
    workspace = request.app.get("workspace")
    if not workspace:
        return
    user_workspace = workspace / "workspaces" / user_id
    # sync_workspace_templates 是同步的，在线程池中运行
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: _sync_user_workspace(user_workspace, user_id),
    )
```

- [ ] **Step 4: 添加 `_sync_user_workspace` 辅助函数**

在 `_error` 函数之后添加:
```python
def _sync_user_workspace(user_workspace: Path, user_id: str) -> None:
    """Sync templates to user workspace with correct cloud storage prefix."""
    from nanobot.utils.helpers import sync_workspace_templates
    storage_prefix = f"workspaces/{user_id}/"
    sync_workspace_templates(user_workspace, silent=True, storage_prefix=storage_prefix)
```

- [ ] **Step 5: 验证导入正常**

运行: `python -c "from nanobot.api.middleware import JWTAuthMiddleware; print('OK')"`
预期: `OK`

- [ ] **Step 6: 运行 middleware 测试**

运行: `pytest tests/api/test_middleware.py -v`
预期: 原有 4 个测试 PASS

- [ ] **Step 7: 提交**

```bash
git add nanobot/api/middleware.py
git commit -m "feat(api): initialize user workspace on first login in JWTAuthMiddleware"
```

---

## Task 3: `create_app` 恢复 `workspace` 参数

**文件:**
- 修改: `nanobot/api/server.py:182-201`

- [ ] **Step 1: 修改 `create_app` 函数签名，恢复 `workspace` 参数**

将 `nanobot/api/server.py:182` 从:
```python
def create_app(agent_loop, *, jwt_secret: str = "", model_name: str = "nanobot", request_timeout: float = 120.0) -> web.Application:
```

改为:
```python
def create_app(agent_loop, *, jwt_secret: str = "", model_name: str = "nanobot", request_timeout: float = 120.0, workspace: "Path | None" = None) -> web.Application:
```

- [ ] **Step 2: 在 `create_app` 内部，添加 `workspace` 到 app dict**

将 `nanobot/api/server.py:190-194` 从:
```python
app = web.Application()
app["agent_loop"] = agent_loop
app["model_name"] = model_name
app["request_timeout"] = request_timeout
app["session_locks"] = {}  # per-user locks, keyed by session_key
```

改为:
```python
app = web.Application()
app["agent_loop"] = agent_loop
app["model_name"] = model_name
app["request_timeout"] = request_timeout
app["session_locks"] = {}  # per-user locks, keyed by session_key
if workspace is not None:
    app["workspace"] = workspace
```

- [ ] **Step 3: 更新 docstring**

将 `nanobot/api/server.py:183-189` 的 docstring 从:
```python
"""Create the aiohttp application.

Args:
    agent_loop: An initialized AgentLoop instance.
    model_name: Model name reported in responses.
    request_timeout: Per-request timeout in seconds.
"""
```

改为:
```python
"""Create the aiohttp application.

Args:
    agent_loop: An initialized AgentLoop instance.
    model_name: Model name reported in responses.
    request_timeout: Per-request timeout in seconds.
    workspace: Base workspace path for user workspace isolation.
"""
```

- [ ] **Step 4: 验证导入正常**

运行: `python -c "from nanobot.api.server import create_app; print('OK')"`
预期: `OK`

- [ ] **Step 5: 运行 API 测试**

运行: `pytest tests/api/test_server.py -v`
预期: 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add nanobot/api/server.py
git commit -m "feat(api): restore workspace parameter to create_app for user isolation"
```

---

## Task 4: `serve` 命令传入 `workspace` 参数

**文件:**
- 修改: `nanobot/cli/commands.py:595`

- [ ] **Step 1: 修改 `serve` 中 `create_app` 调用，传入 `workspace` 参数**

将 `nanobot/cli/commands.py:595` 从:
```python
api_app = create_app(agent_loop, jwt_secret=jwt_secret, model_name=model_name, request_timeout=timeout)
```

改为:
```python
api_app = create_app(agent_loop, jwt_secret=jwt_secret, model_name=model_name, request_timeout=timeout, workspace=agent_loop.workspace)
```

- [ ] **Step 2: 运行 CLI 测试**

运行: `pytest tests/cli/test_commands.py -v -k "serve" --no-header -q`
预期: PASS

- [ ] **Step 3: 提交**

```bash
git add nanobot/cli/commands.py
git commit -m "feat(cli): pass workspace to create_app in serve command"
```

---

## Task 5: 新增 workspace 初始化测试

**文件:**
- 修改: `tests/api/test_middleware.py`

- [ ] **Step 1: 添加 workspace 初始化测试**

在 `tests/api/test_middleware.py` 末尾添加:

```python
async def test_workspace_initialized_on_first_login(tmp_path):
    """Verify user workspace is created with templates on first authenticated request."""
    from nanobot.api.middleware import JWTAuthMiddleware
    import jwt

    workspace = tmp_path / ".nanobot"
    workspace.mkdir()

    async def handler(request):
        return web.json_response({"ok": True})

    middleware = JWTAuthMiddleware("test-secret")
    app = web.Application(middlewares=[middleware], handler=handler)
    app["workspace"] = workspace
    # 直接添加路由而不是通过 middleware 包装
    app.router.add_get("/test", handler)

    # 注入 middleware
    app.middlewares = [middleware]

    token = _make_token({"userId": "alice"}, "test-secret")
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/test", headers={"Authorization": f"Bearer {token}"})
        assert resp.status == 200

    # 验证用户 workspace 目录已创建
    user_ws = workspace / "workspaces" / "alice"
    assert user_ws.exists(), f"User workspace not created: {user_ws}"
    assert (user_ws / "SOUL.md").exists(), "SOUL.md not created"
    assert (user_ws / "USER.md").exists(), "USER.md not created"
    assert (user_ws / "memory" / "MEMORY.md").exists(), "MEMORY.md not created"


async def test_workspace_init_idempotent(tmp_path):
    """Verify workspace initialization is idempotent (second login doesn't error)."""
    from nanobot.api.middleware import JWTAuthMiddleware
    import jwt

    workspace = tmp_path / ".nanobot"
    workspace.mkdir()
    user_ws = workspace / "workspaces" / "alice"
    user_ws.mkdir(parents=True)
    # 预先创建一些文件
    (user_ws / "SOUL.md").write_text("existing content")

    async def handler(request):
        return web.json_response({"ok": True})

    middleware = JWTAuthMiddleware("test-secret")
    app = web.Application(middlewares=[middleware])
    app["workspace"] = workspace
    app.router.add_get("/test", handler)

    token = _make_token({"userId": "alice"}, "test-secret")
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/test", headers={"Authorization": f"Bearer {token}"})
        assert resp.status == 200
        # 原有内容应保留
        assert (user_ws / "SOUL.md").read_text() == "existing content"
```

注意: `aiohttp.test_utils.TestClient` 的构造函数需要传入 `TestServer(app)`，但 middleware 测试中 `app` 已经通过 `middlewares=[middleware]` 注册了 middleware，所以 routes 直接加到 `app` 上即可。

- [ ] **Step 2: 运行新增测试验证**

运行: `pytest tests/api/test_middleware.py::test_workspace_initialized_on_first_login -v`
运行: `pytest tests/api/test_middleware.py::test_workspace_init_idempotent -v`
预期: 两个测试 PASS

- [ ] **Step 3: 运行全部 middleware 测试**

运行: `pytest tests/api/test_middleware.py -v`
预期: 全部 6 个测试 PASS

- [ ] **Step 4: 提交**

```bash
git add tests/api/test_middleware.py
git commit -m "test(api): add workspace initialization tests for JWTAuthMiddleware"
```

---

## Task 6: 验证完整集成

- [ ] **Step 1: 运行所有 API 测试**

运行: `pytest tests/api/ -v`
预期: 全部 PASS

- [ ] **Step 2: 运行 CLI 相关测试**

运行: `pytest tests/cli/test_commands.py -v -k "serve" --no-header -q`
预期: PASS

- [ ] **Step 3: 手动冒烟测试**

```bash
python -c "
from nanobot.api.middleware import JWTAuthMiddleware
from nanobot.api.server import create_app
from nanobot.utils.helpers import sync_workspace_templates
print('All imports OK')
"
```

- [ ] **Step 4: 提交所有剩余更改**

```bash
git add -A
git status
```

---

## 需求覆盖检查

- [ ] JWT 验签成功后初始化 workspace — Task 2
- [ ] `sync_workspace_templates` 支持 `storage_prefix` — Task 1
- [ ] 云存储 key 前缀 `workspaces/{user_id}/` — Task 1
- [ ] 本地文件系统 fallback — Task 1
- [ ] 幂等初始化（`_storage.exists()` 检查）— Task 1
- [ ] `create_app` 接受 `workspace` 参数 — Task 3
- [ ] `serve` 命令传入 `workspace` — Task 4
- [ ] 单元测试覆盖 — Task 5
