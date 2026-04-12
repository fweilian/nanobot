# Test Spec: Stateless Multi-Instance Cloud Refactor

## Verification Strategy

本次规划的验证重点不是“已有单实例 happy path”，而是：

- 实例本地真正无长期状态
- Redis session 成为在线主状态
- Redis 锁在多实例并发写时快速失败
- S3 继续承担 durable workspace 层

## Test Areas

### 1. Redis session store

- 同一 `user + agent + session_id` 可从 Redis 恢复最近上下文
- 不同实例读取同一 Redis session 得到一致结果
- session checkpoint/cleanup 在 Redis 上语义正确

### 2. Redis distributed lock

- 第一个写请求获取锁成功
- 第二个并发写请求对同一 scope 获取锁失败
- 锁释放后后续请求可继续
- 锁 TTL 超时后不会永久卡死

### 3. Fast-fail conflict behavior

- 对同一 `user + agent + session_id` 的第二个写请求返回明确冲突
- 响应体包含 retryable 语义
- 服务端不做排队等待

### 4. Request-scoped temporary workspace

- 请求执行前创建临时目录
- 请求结束后目录被清理
- 实例重启不依赖保留 `cache/users/{user_id}` 才能继续服务

### 5. S3 durable workspace sync

- 必需 durable 文件从 S3 拉到临时目录
- 修改后的 durable 文件可写回 S3
- 非 durable 临时文件不会错误长期保留

### 6. Brownfield compatibility

- 现有 `AgentLoop` 仍可在请求级临时目录运行
- cloud API 现有接口形状不被破坏
- local-mode 路径不回归

### 7. Multi-instance simulation

- 模拟两个独立 runtime/service 实例，共享同一 Redis + S3
- 同一 session 的连续请求可以打到不同实例
- 并发写场景下快速失败行为一致

## Initial Test Shape

### Unit tests

- `tests/cloud/test_session_store.py`
- `tests/cloud/test_locking.py`
- `tests/cloud/test_workspace_sync.py`

### Integration tests

- `tests/cloud/test_server_conflicts.py`
- `tests/cloud/test_multi_instance_flow.py`

### Regression tests

- 保留并扩展：
  - `tests/cloud/test_server.py`
  - `tests/cloud/test_workspace.py`
  - `tests/test_openai_api.py`

## Example Verification Commands

- `pytest tests/cloud/test_session_store.py -q`
- `pytest tests/cloud/test_locking.py -q`
- `pytest tests/cloud/test_server_conflicts.py -q`
- `pytest tests/cloud/test_multi_instance_flow.py -q`
- `pytest tests/test_openai_api.py -q`
- `ruff check nanobot/cloud tests/cloud`

## Done Criteria

- 同一 session 的跨实例请求不依赖实例本地长期缓存
- Redis session 在线真源语义被测试覆盖
- 锁冲突快速失败语义被测试覆盖
- 请求级临时目录生命周期被测试覆盖
- 现有 local-mode API 回归测试仍通过
