# Deep Interview Context Snapshot

- Task slug: `cloud-stateless-multi-instance`
- Timestamp (UTC): `20260412T050106Z`
- Profile: `standard`
- Context type: `brownfield`

## Task Statement

给出一个面向“多实例、无状态、无会话粘性”的 cloud 重构方案。

## Desired Outcome

形成一份可执行的重构规格，说明如何把当前 cloud 模块从“本地缓存镜像 + S3 回写”的实现演进为真正适合生产的无状态多实例架构。

## Stated Solution

用户明确的生产前提：

- 多实例
- 无状态服务
- 无会话粘性
- 请求会随机落到任意实例

## Probable Intent Hypothesis

避免当前 cloud 实现直接带着单实例/弱状态假设进入生产，提前明确状态分层、缓存策略、并发控制和会话架构。

## Known Facts / Evidence

- 当前 cloud 模块在 `nanobot/cloud/runtime.py` 中通过 `ensure_user_workspace()` 下载用户工作区到本地缓存目录。
- 当前 cloud 请求执行前还会创建 runtime 临时副本，再运行 `AgentLoop`，最后把本地改动回写到缓存目录和 S3。
- 当前 cloud 文档 `docs/CLOUD.md` 已声明 platform-config 是本地文件路径，而用户 workspace 存在 S3。
- 当前 session 仍然通过 workspace 文件体系持久化，而不是外部会话存储。
- 当前 cloud 方案更接近单实例/低并发/开发环境友好的适配层。

## Constraints

- 当前问题是“给出重构方案”，不是直接实现
- 需要基于现有 cloud brownfield 实现来重构，而不是纯 greenfield
- 用户已经明确生产前提：多实例、无状态、无会话粘性

## Unknowns / Open Questions

- 高频会话状态最终希望落在哪里：Redis、数据库、还是仍接受对象存储
- 数据库是否已经是可接受依赖，还是希望尽量减少基础设施种类
- 是否要求强一致并发保护，还是接受乐观并发 + 冲突失败
- 第一阶段重构是否允许保留“部分文件仍落 S3”，还是要一次性把 session 与 metadata 全部拆出去

## Decision-Boundary Unknowns

- OMX 在方案中是否可自行引入 Redis / Postgres 作为新基础设施
- 是否可把当前 `workspaces/{user_id}/config.json` 迁移成 DB metadata + S3 文件混合模式
- 是否要求兼容现有 S3 路径结构，还是允许重排对象布局

## Likely Codebase Touchpoints

- `nanobot/cloud/runtime.py`
- `nanobot/cloud/storage.py`
- `nanobot/cloud/server.py`
- `docs/CLOUD.md`
- `test_cloud_api.py`

## Brownfield Evidence Notes

- 当前实现的本地缓存主要是为了复用现有 `AgentLoop` / `SessionManager` / `SkillsLoader` 的本地文件系统语义。
- 用户的新生产约束意味着本地缓存最多只能保留请求级临时作用，不能再承担跨请求状态语义。
