# JWT 认证 API 设计

## 1. 目标

为对话聊天 API（`/v1/chat/completions`）添加 JWT 认证，用户 ID 通过外部 IdP 签发的 JWT 解析获取，实现用户级 workspace 隔离。

## 2. 架构

```
HTTP 请求 (Authorization: Bearer <jwt>)
    ↓
JWTAuthMiddleware:
    - 提取 Authorization header
    - 用共享密钥验签 (HS256)
    - 从 body['userId'] 提取 user_id
    - 写入 request['user_id']
    ↓ (验签失败 → 401)
handle_chat_completions:
    - 从 request['user_id'] 获取 user_id
    - 构建 InboundMessage(sender_id=user_id, ...)
    - 调用 agent_loop.process_direct(...)
```

## 3. JWT 验签

| 项目 | 值 |
|------|-----|
| 传输方式 | `Authorization: Bearer <token>` |
| 算法 | HS256 |
| 验签密钥 | 配置项 `jwt.secret`（共享密钥） |
| user_id 字段 | `body['userId']`（自定义 claim，驼峰命名） |
| 过期校验 | 不校验（`options={"verify_exp": False}`） |
| 其他 claims | 不校验 |

## 4. JWT 配置

`nanobot/config/schema.py` 新增：

```python
class JWTConfig(BaseModel):
    secret: str
```

`config.json` 格式：

```json
{
  "jwt": {
    "secret": "${JWT_SECRET}"
  }
}
```

## 5. 改动点

| 文件 | 改动 |
|------|------|
| `nanobot/api/middleware.py`（新建） | JWTAuthMiddleware，实现 JWT 验签 |
| `nanobot/api/server.py` | 注册 middleware，从 `request['user_id']` 获取 user_id 传入 `process_direct` |
| `nanobot/config/schema.py` | 添加 `JWTConfig` 模型 |

## 6. session_key 和 workspace 隔离

保持现有 `session_key = f"api:{body['session_id']}"` 格式，workspace 隔离完全由 `sender_id`（从 JWT `userId` 提取）处理，落在 `workspaces/{sender_id}/` 路径。

## 7. 错误处理

| 场景 | HTTP 状态码 | 错误信息 |
|------|-------------|----------|
| 缺少/无效 Authorization header | 401 | "Missing or invalid Authorization header" |
| JWT 签名验证失败 | 401 | "Invalid token" |
| 缺少 userId claim | 401 | "Missing userId in token" |
| 其他异常 | 401 | "Unauthorized" |

## 8. 兼容性

- **CLI 模式**：不使用 JWT，仍然通过 channel 层传入 `sender_id`
- **无 jwt 配置**：API server 不启动（jwt 配置必填）
