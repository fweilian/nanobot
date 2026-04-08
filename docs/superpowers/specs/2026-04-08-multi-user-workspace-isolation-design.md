# 多用户 Workspace 隔离设计

## 1. 目标

支持多用户会话，每个用户通过 `sender_id` 区分，workspace 完全隔离。

## 2. 路径结构

```
~/.nanobot/
├── workspaces/
│   ├── {sender_id}/           <- 用户隔离 workspace
│   │   ├── SOUL.md
│   │   ├── USER.md
│   │   ├── memory/
│   │   │   ├── MEMORY.md
│   │   │   └── history.jsonl
│   │   ├── skills/
│   │   └── .nanobot/          <- tool-results 等
│   └── ...
└── config.json
```

云存储时 key 前缀变为：`{prefix}workspaces/{sender_id}/`

## 3. 核心机制

### 3.1 ContextVar 存储当前用户

在 `nanobot/utils/user_context.py`（新建）：

```python
from contextvars import ContextVar

_current_user_id: ContextVar[str | None] = ContextVar("current_user_id", default=None)

def set_current_user_id(user_id: str | None) -> None: ...
def get_current_user_id() -> str | None: ...
```

### 3.2 AgentLoop 设置用户上下文

```python
async def _dispatch(self, msg: InboundMessage) -> None:
    set_current_user_id(msg.sender_id)  # <- 在锁之前设置
    try:
        # ... 处理逻辑
    finally:
        set_current_user_id(None)  # <- 清理
```

### 3.3 文件系统工具路径注入

`_FsTool._resolve()` 和 `_storage_key()` 读取 `get_current_user_id()`，对相对路径注入 userId 前缀：

- **本地**：`workspace` 根变为 `~/.nanobot/workspaces/{sender_id}/`
- **CloudStorage key**：同样 prefix

### 3.4 存储层适配

`LocalStorage` 和 `S3CompatibleStorage` 的 key 自然带上 userId 前缀，无需额外抽象。

### 3.5 模板同步

`sync_workspace_templates` 按 userId 同步到各自 workspace 目录。

## 4. 隔离范围

| 数据 | 隔离方式 |
|------|----------|
| Workspace 目录 | `workspaces/{sender_id}/` |
| File tool 结果 | `workspaces/{sender_id}/.nanobot/tool-results/` |
| Memory/History | `workspaces/{sender_id}/memory/` |
| Sessions | 共用（session key 不变） |

## 5. 兼容性

- **CLI 模式**：`sender_id="cli"` 或 `None`，降级到 `~/.nanobot/workspace`
- **单用户配置**：`workspace` 配置项被忽略，固定使用 `workspaces/` 结构
- **现有 session**：session key 保持 `channel:chat_id`，无需迁移

## 6. 改动点

1. **新增** `nanobot/utils/user_context.py` — ContextVar 管理
2. **修改** `nanobot/agent/loop.py` — `_dispatch` 设置/清理 user_id context
3. **修改** `nanobot/agent/tools/filesystem.py` — `_FsTool` 路径解析支持 userId 前缀
4. **修改** `nanobot/utils/helpers.py` — `maybe_persist_tool_result` 支持 userId
5. **修改** `nanobot/providers/cloud_storage.py` — 无需改动（key 前缀由工具层注入）
6. **修改** `nanobot/agent/context.py` — memory store path 支持 userId
7. **修改** `nanobot/session/manager.py` — SessionManager 使用 user-scoped workspace
