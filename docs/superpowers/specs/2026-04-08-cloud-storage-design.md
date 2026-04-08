# 云端存储支持设计

## 背景

nanobot 当前所有持久化数据存储在本地磁盘（workspace 目录）。在云端部署场景下，机器无本地存储，需要将数据迁移至云对象存储（COS）。

## 目标

通过 `config.json` 配置切换存储后端，支持 COS（腾讯云对象存储），存储路径前缀为 `mclaw/`。

---

## 1. 配置结构

在 `config.json` 新增 `cloud_storage` 节点：

```json
{
  "workspace": "~/.nanobot/workspace",
  "cloud_storage": {
    "provider": "cos",
    "endpoint_url": "https://cos.ap-beijing.myqcloud.com",
    "bucket": "your-bucket-name",
    "region": "ap-beijing",
    "secret_id": "${COS_SECRET_ID}",
    "secret_key": "${COS_SECRET_KEY}",
    "prefix": "mclaw/"
  }
}
```

- `cloud_storage` 存在时启用云端存储；不存在时保持现有本地 `workspace` 行为（完全向后兼容）
- `secret_id` / `secret_key` 支持 `${ENV_VAR}` 环境变量插值（复用现有机制）
- `region` 字段保留，实际 `endpoint_url` 用固定值
- `provider` 支持 `cos`（未来可扩展 `s3` / `minio` 等）

配置模型定义在 `nanobot/config/schema.py` 新增 `CloudStorageConfig` Pydantic 模型。

---

## 2. CloudStorage 接口

```python
class CloudStorage(Protocol):
    def read(self, key: str) -> bytes: ...
    def write(self, key: str, data: bytes) -> None: ...
    def list(self, prefix: str) -> list[str]: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
```

- `key` 是相对于 `prefix` 的路径，如 `memory/history.jsonl`
- 所有方法同步，不做缓存，不做幂等重试（由上层处理）
- 用 `Protocol` 定义接口类型，便于测试时 mock

---

## 3. S3 兼容实现

```python
# nanobot/providers/cloud_storage.py
class S3CompatibleStorage:
    def __init__(self, config: CloudStorageConfig): ...
    def read(self, key: str) -> bytes: ...
    def write(self, key: str, data: bytes) -> None: ...
    def list(self, prefix: str) -> list[str]: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...
```

实现细节：

- 用 `boto3` + `botocore`（标准 S3 SDK）
- `endpoint_url` 直接使用配置值（腾讯云 COS 兼容 S3 API）
- `prefix` 在 `S3CompatibleStorage` 内部拼接到每个 key 前
- 放在 `nanobot/providers/` 目录下（与现有 provider 架构一致）

存储路径映射示例：
- 本地 `memory/history.jsonl` → COS `mclaw/memory/history.jsonl`
- 本地 `sessions/abc123.jsonl` → COS `mclaw/sessions/abc123.jsonl`
- 本地 `.nanobot/tool-results/sess/tool-call-id.txt` → COS `mclaw/.nanobot/tool-results/sess/tool-call-id.txt`

---

## 4. 存储切换机制

初始化时 `StorageBackendFactory` 根据 `cloud_storage` 配置是否存在，返回 `LocalStorage` 或 `S3CompatibleStorage`：

```python
# nanobot/providers/cloud_storage.py
def create_storage(config: CloudStorageConfig | None) -> CloudStorage:
    if config is None:
        return LocalStorage()  # 现有本地行为
    return S3CompatibleStorage(config)
```

所有文件操作统一通过 `CloudStorage` 接口，不关心底层是本地还是 COS。

---

## 5. 受影响的现有模块

| 模块 | 当前行为 | 改动方式 |
|---|---|---|
| `MemoryStore` | `workspace / "memory"` 本地文件读写 | 注入 `CloudStorage`，路径拼接改为 `storage.list()` 等 |
| `SessionManager` | `workspace / "sessions/*.jsonl"` | 同上 |
| `ToolResultPersistence` | `.nanobot/tool-results/` | 同上 |
| `GitStore` | 本地 `.git` 目录版本控制 | 云端模式下 `is_available() → False`，相关调用 skip |
| `sync_workspace_templates` | 写本地文件 | 改为 `storage.write()` |

改造顺序：
1. `CloudStorage` 接口 + `S3CompatibleStorage` 实现
2. `StorageBackendFactory`
3. `MemoryStore`（核心记忆层）
4. `SessionManager`
5. `ToolResultPersistence`
6. `GitStore`（云端禁用）
7. `sync_workspace_templates`

每次改造只改文件 I/O 部分，业务逻辑不变。

---

## 6. COS Bucket 文件结构

```
mclaw/
├── SOUL.md
├── USER.md
├── memory/
│   ├── MEMORY.md
│   ├── history.jsonl
│   ├── .cursor
│   └── .dream_cursor
├── sessions/
│   └── {safe_key}.jsonl
└── .nanobot/
    └── tool-results/
        └── {session}/{tool_call_id}.txt
```

Session 文件结构保持现有扁平结构不变（`sessions/{safe_key}.jsonl`），便于后续分用户改造。

---

## 7. GitStore 处理

云端模式下 GitStore 禁用：

```python
def is_available(self) -> bool:
    if is_cloud_storage():
        return False
    return super().is_available()
```

`Dream` 等依赖 GitStore 的模块在 GitStore 不可用时静默跳过，不影响主流程。

---

## 8. 测试策略

- `CloudStorage` 接口定义清晰，便于 mock
- `S3CompatibleStorage` 核心方法（read/write/list/exists/delete）各有同步测试
- 集成测试可使用 `moto`（S3 mock）或 LocalStack
- 本地模式保持原有测试不变
