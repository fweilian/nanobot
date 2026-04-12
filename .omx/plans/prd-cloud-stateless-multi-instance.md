# PRD: Stateless Multi-Instance Cloud Refactor

## Overview

将现有 `nanobot.cloud` 从“实例本地缓存用户镜像 + runtime 副本 + S3 回写”的实现，重构为面向生产的多实例无状态服务。

第一阶段明确限定为：

- `Redis + S3`
- 不引入数据库
- 无会话粘性
- 同一请求可随机落到任意实例

## Problem

当前 cloud 模块虽然已经具备：

- FastAPI API
- OAuth/OIDC bearer token 鉴权
- 多用户、多 agent
- S3-backed workspace

但它仍然保留了明显的单实例/弱状态假设：

- 实例本地缓存目录承载了跨请求语义
- session 仍通过 workspace 文件体系表达
- 并发控制没有被定义成面向多实例的远端协议
- 用户工作区在每个实例上可能形成不同步的本地副本

在“多实例、无状态、无会话粘性”的生产模型下，这会带来：

- 会话连续性依赖实例本地
- 跨实例并发写冲突
- 本地磁盘容量不受控
- 随机实例调度下的状态不一致

## Goals

1. 让 cloud 服务实例真正无状态。
2. 把在线高频状态迁到 Redis。
3. 保留 S3 作为 workspace / 文件 / 长期归档层。
4. 定义第一阶段的请求级临时工作目录模型。
5. 为并发写冲突建立清晰、可测试的快速失败语义。
6. 给出现有 `nanobot.cloud` 的迁移路径，而不是推倒重来。

## Non-Goals

- 第一阶段不引入数据库
- 不做跨实例并发写冲突自动合并
- 不做所有 workspace 文件的对象级按需读取
- 不展开 Redis 持久化、HA、灾备设计
- 不直接实现第二阶段/第三阶段能力

## Product Decision Summary

- 基础设施：`Redis + S3`
- Redis 负责：
  - 在线 session
  - 分布式锁
  - 幂等辅助状态
- S3 负责：
  - user workspace 文件
  - agent 配置文件
  - 长期归档与大文件
- 本地磁盘只负责：
  - 当前请求的临时运行目录
- 并发写策略：
  - 对同一 `user_id + agent_name + session_id` 的第二个写请求，快速失败
  - 不排队
  - 不自动合并

## User Stories

### US-001 Stateless instance safety

作为平台部署者，我希望任意 cloud 实例都不依赖本地历史状态，这样请求可以随机打到任意实例。

Acceptance Criteria:

- 实例本地不保留跨请求用户镜像作为主状态
- 服务重启不需要恢复本地缓存即可继续服务

### US-002 Redis-backed online session

作为在线对话系统，我希望高频会话状态在 Redis 中维护，这样不同实例可以接续同一个会话。

Acceptance Criteria:

- 在线 session 主状态不再依赖 workspace 文件作为实时真源
- 任意实例都能从 Redis 恢复同一 `user + agent + session_id` 的对话上下文

### US-003 Redis-backed distributed locking

作为云端写路径，我希望并发写请求有明确的分布式锁语义，以避免跨实例覆盖。

Acceptance Criteria:

- 对同一写作用域定义 Redis 锁键
- 第二个并发写请求默认快速失败
- 返回明确的冲突语义和重试建议

### US-004 S3-backed durable workspace

作为系统，我希望 workspace 文件继续留在 S3，这样长期文件与大对象不依赖实例本地盘。

Acceptance Criteria:

- user config / agent config / skill 文件 / memory 文件仍可通过 S3 持久化
- 本地磁盘只作为请求执行期临时工作目录

### US-005 Brownfield-compatible execution bridge

作为开发团队，我希望第一阶段仍能复用现有 `AgentLoop`，这样无需一次性重写核心 runtime。

Acceptance Criteria:

- 允许请求级临时工作目录
- 现有 `AgentLoop` / `SkillsLoader` / filesystem tools 能继续工作
- 运行期结束后本地临时目录被清理

## Architecture Direction

### 1. State partitioning

#### Redis

职责：

- session 主状态
- session 活跃游标/最近消息
- 分布式锁
- 幂等键
- 可选的短期 checkpoint

#### S3

职责：

- `workspaces/{user_id}/config.json`
- `workspaces/{user_id}/agents/{agent_name}/config.json`
- agent/workspace skills
- memory 文件
- 需要长期保留的工作区文件
- 长期归档内容

#### Local ephemeral filesystem

职责：

- 当前请求的临时运行目录
- 生命周期仅覆盖单请求

### 2. Request lifecycle

写请求（如 `POST /v1/chat/completions`）的目标流程：

1. 校验 bearer token，得到 `user_id`
2. 解析 `agent`、`session_id`
3. 获取 Redis 分布式锁：
   - scope: `user_id + agent_name + session_id`
4. 若锁获取失败：
   - 返回冲突错误（推荐 `409` 或可评估 `429`）
5. 从 Redis 读取在线 session 状态
6. 从 S3 拉取当前请求需要的最小工作区文件到临时目录
7. 在临时目录中运行现有 `AgentLoop`
8. 将 durable 文件写回 S3
9. 将在线 session 更新写回 Redis
10. 释放锁
11. 删除临时目录

读接口（如 `/v1/agents`、`/v1/models`）：

- 不需要 session 写锁
- 直接读 S3 配置或平台配置

### 3. Locking semantics

#### Lock scope

第一阶段推荐默认粒度：

- `lock:chat:{user_id}:{agent_name}:{session_id}`

原因：

- 粒度足够小
- 不会把同一用户的所有会话都串行化
- 与当前 session 语义一致

#### Behavior

- 获取成功：继续请求
- 获取失败：快速失败
- 不等待
- 不做合并

#### Error shape

建议：

- HTTP: `409 Conflict`
- body:
  - `error.code = "session_locked"`
  - `error.message = "Another write request is already in progress for this session."`
  - `error.retryable = true`

### 4. Session model

第一阶段建议把 session 拆成两层：

#### Redis online session

用于：

- 最近消息窗口
- 当前活跃 turn 状态
- 快速续接

#### S3 long-term archive

用于：

- 归档历史
- 长期保留/审计类内容

第一阶段允许：

- Redis 为在线真源
- S3 为归档副本

不再要求 workspace 文件中的 session 是在线主真源。

### 5. Workspace model in phase 1

第一阶段仍然允许请求级临时工作目录。

但必须改变两个关键点：

- 不保留长期 `cache/users/{user_id}` 目录作为主语义
- 请求结束后必须清理临时目录

也就是说：

- 可以有 `/tmp/nanobot-cloud/{request_id}` 或等价临时目录
- 不应该存在“每实例长期保留用户镜像”

### 6. Config/source of truth

第一阶段在无数据库前提下：

- 用户配置索引仍可继续使用 S3 中的 `workspaces/{user_id}/config.json`
- agent 配置仍可继续使用 `workspaces/{user_id}/agents/{agent_name}/config.json`
- platform-config 仍为服务节点本地文件

## Proposed Modules / Refactor Boundaries

### `cloud/session_store.py`

新增 Redis-backed session store：

- `load_session()`
- `save_session()`
- `append_messages()`
- `load_recent_history()`
- `set_checkpoint()`
- `clear_checkpoint()`

### `cloud/lock.py`

新增 Redis lock abstraction：

- `acquire(scope, ttl)`
- `release(token)`
- `is_locked(scope)`

### `cloud/workspace_sync.py`

替代当前“长期缓存 + runtime 副本”模型：

- `prepare_request_workspace(user_id, agent_name, request_id)`
- `sync_required_files_from_s3(...)`
- `sync_durable_outputs_to_s3(...)`
- `cleanup_request_workspace(...)`

### `cloud/runtime.py`

重构为 orchestration 层：

- 组合 auth / session / lock / workspace sync / agent execution
- 不再承担长期用户缓存语义

### `cloud/server.py`

补充：

- 锁冲突错误码
- session store 接线
- 幂等/冲突语义

## Migration Plan

### Phase A: Protocol carve-out

- 抽出 Redis session store 接口
- 抽出 Redis lock 接口
- 不立刻改全部执行路径

### Phase B: Session truth migration

- 在线 session 从 workspace 文件主语义迁到 Redis
- workspace 中 session 文件降级为长期归档/兼容数据

### Phase C: Ephemeral workspace-only execution

- 移除长期 `cache/users/{user_id}` 模型
- 改为单请求临时目录
- 请求结束后清理

### Phase D: Conflict semantics hardening

- `/v1/chat/completions` 等写接口统一使用 Redis 分布式锁
- 冲突统一快速失败

### Phase E: Observability and tuning

- 指标：锁冲突率、Redis session 命中率、S3 拉取体积、临时目录大小、请求失败率

## Risks

- Redis session 与 S3 归档的双层语义需要边界清晰，否则容易再次混淆“谁是真源”
- 第一阶段仍依赖本地临时目录，极大 workspace 请求仍可能有单请求磁盘压力
- 快速失败策略需要调用端接受重试语义
- 无数据库前提下，复杂元数据查询能力仍较弱

## Open Design Questions For Next Planning Step

- Redis session 数据结构采用 JSON blob 还是 list/hash 分片
- 锁 TTL、续期策略、超时边界如何默认
- session 归档写回的节奏：每轮、每请求、还是批量
- 哪些文件属于“durable outputs”，哪些只存在于临时目录

## Delivery Slices

1. 设计 Redis session / lock 边界
2. 抽离 request-scoped workspace sync
3. 改造 `cloud.runtime` 为无长期本地镜像
4. 增加锁冲突错误和回归测试
5. 增加多实例模拟测试
