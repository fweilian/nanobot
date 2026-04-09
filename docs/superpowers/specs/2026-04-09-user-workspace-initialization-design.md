# 用户 Workspace 初始化设计

## 1. 目标

在用户首次通过 API（JWT 认证）登录后，自动初始化该用户的 workspace，包含 SOUL.md、USER.md、memory/ 等模板文件，支持本地和云端（COS/S3）两种存储模式。

## 2. 背景

nanobot 支持多用户 workspace 隔离（`workspaces/{user_id}/`）。用户首次登录时，其 workspace 目录尚未创建，需要自动初始化模板文件。

根 workspace 模板同步在应用启动时已完成（`sync_workspace_templates(runtime_config.workspace_path)`），多用户 workspace 初始化需要在请求时按需触发。

## 3. 架构

```
JWT 验签成功
    ↓
JWTAuthMiddleware._ensure_user_workspace(user_id)
    ↓
sync_workspace_templates(user_workspace_dir, storage_prefix="workspaces/{user_id}/")
    ↓
本地: ~/.nanobot/workspaces/{user_id}/SOUL.md, USER.md, memory/, skills/
云端: mclaw/workspaces/{user_id}/SOUL.md, USER.md, memory/, ...
```

## 4. 存储结构

| 存储模式 | 文件 key 示例 |
|----------|--------------|
| 本地 | `~/.nanobot/workspaces/alice/SOUL.md` |
| 云端 | `mclaw/workspaces/alice/SOUL.md` |

其中 `mclaw/` 是 `cloud_storage.prefix` 配置。

## 5. 改动点

### 5.1 `helpers.sync_workspace_templates` 增加 `storage_prefix` 参数

**文件**: `nanobot/utils/helpers.py`

**签名变更**:
```python
def sync_workspace_templates(
    workspace: Path,
    silent: bool = False,
    storage_prefix: str = "",   # 新增参数：云存储 key 前缀，如 "workspaces/{user_id}/"
) -> list[str]:
```

**`_write` 内部变更**（第 491-505 行）:
- 原来: `_write(item, workspace / item.name, item.name)`
- 改为: `_write(item, workspace / item.name, f"{storage_prefix}{item.name}")`

**行为**:
- `storage_prefix = ""`（默认）: 本地模式，`_write` 跳过 cloud storage 写入
- `storage_prefix = "workspaces/alice/"`: 云存储 key 变为 `mclaw/workspaces/alice/SOUL.md`

**幂等性**: `_storage.exists(storage_key)` 检查已存在则跳过。

### 5.2 `JWTAuthMiddleware` 调用 workspace 初始化

**文件**: `nanobot/api/middleware.py`

**变更**:
1. 恢复 `workspace` 参数传入 `create_app`
2. 在 `__call__` 验签成功后，调用 `_ensure_user_workspace`
3. `_ensure_user_workspace` 调用 `sync_workspace_templates(user_workspace, storage_prefix=...)`

**代码**:
```python
async def _ensure_user_workspace(self, request: web.Request, user_id: str) -> None:
    workspace = request.app.get("workspace")
    if not workspace:
        return
    user_workspace = workspace / "workspaces" / user_id
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: _sync_user_workspace(user_workspace, user_id),
    )
```

### 5.3 新增 `_sync_user_workspace` 函数

**文件**: `nanobot/api/middleware.py`（或 `nanobot/utils/workspace.py`）

```python
def _sync_user_workspace(user_workspace: Path, user_id: str) -> None:
    from nanobot.utils.helpers import sync_workspace_templates
    storage_prefix = f"workspaces/{user_id}/"
    sync_workspace_templates(user_workspace, silent=True, storage_prefix=storage_prefix)
```

> 注: `_storage` 全局变量在 middleware 处理请求时已由 `set_storage()` 初始化完毕（第 550 行），可直接使用。

### 5.4 `create_app` 恢复 `workspace` 参数

**文件**: `nanobot/api/server.py`

```python
def create_app(
    agent_loop,
    *,
    jwt_secret: str = "",
    model_name: str = "nanobot",
    request_timeout: float = 120.0,
    workspace: "Path | None" = None,   # 恢复
) -> web.Application:
```

`workspace` 存入 `app["workspace"]` 供 middleware 读取。

## 6. 云存储 key 构造流程

```
user_id = "alice"
storage_prefix = "workspaces/alice/"

SOUL.md → key = "workspaces/alice/SOUL.md"
         → full key = "{prefix}workspaces/alice/SOUL.md"
         → "mclaw/workspaces/alice/SOUL.md"

memory/MEMORY.md → key = "workspaces/alice/memory/MEMORY.md"
                → full key = "mclaw/workspaces/alice/memory/MEMORY.md"
```

## 7. 兼容性

- **CLI 模式**: 不受影响，workspace 初始化在 API 层
- **无 cloud_storage 配置**: `storage_prefix=""`，走本地文件系统路径
- **已有 workspace 用户**: `_storage.exists()` 检查通过，幂等跳过

## 8. 测试要点

| 场景 | 预期 |
|------|------|
| 新用户首次登录 | workspace 目录创建，模板文件写入 |
| 老用户再次登录 | 幂等跳过，不重复写入 |
| 无 cloud_storage（纯本地） | 写入本地 `~/.nanobot/workspaces/{user_id}/` |
| 有 cloud_storage | 写入 `mclaw/workspaces/{user_id}/` |
| middleware 在 `_storage` 未初始化时调用 | 不可能发生（启动顺序保证） |

## 9. 涉及文件

| 文件 | 改动 |
|------|------|
| `nanobot/utils/helpers.py` | `sync_workspace_templates` 增加 `storage_prefix` 参数 |
| `nanobot/api/middleware.py` | 恢复 workspace 初始化逻辑，调用 `sync_workspace_templates` |
| `nanobot/api/server.py` | 恢复 `workspace` 参数 |
| `nanobot/cli/commands.py` | `create_app` 传入 `workspace=agent_loop.workspace` |
| `tests/api/test_middleware.py` | 新增 workspace 初始化测试 |
