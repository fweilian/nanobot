# Deep Interview Spec: Stateless Multi-Instance Cloud Refactor

## Metadata

- Profile: `standard`
- Rounds: `4`
- Final ambiguity: `8.85%`
- Threshold: `20%`
- Context type: `brownfield`
- Context snapshot: `.omx/context/cloud-stateless-multi-instance-20260412T050106Z.md`
- Transcript: `.omx/interviews/cloud-stateless-multi-instance-20260412T050106Z.md`

## Clarity Breakdown

| Dimension | Score |
| --- | --- |
| Intent | 0.88 |
| Outcome | 0.91 |
| Scope | 0.95 |
| Constraints | 0.97 |
| Success Criteria | 0.88 |
| Context | 0.86 |

## Intent

把现有基于“本地缓存镜像 + runtime 副本 + S3 回写”的 cloud 方案重构为真正适合生产的多实例无状态架构，使实例本地不再承担跨请求状态语义。

## Desired Outcome

形成一份第一阶段可落地的重构方案，说明如何把 cloud 模块演进为：

- 多实例
- 无状态服务
- 无会话粘性
- 在线高频状态通过 Redis 管理
- 工作区/长期文件通过 S3 管理
- 请求可随机打到任意实例而不依赖实例本地历史

## In Scope

- 重构 cloud 方案的状态分层
- 明确 Redis 在 session / 锁 / 幂等中的职责
- 明确 S3 在 workspace / 长期归档中的职责
- 保留第一阶段请求级临时工作目录
- 定义并发写锁行为与冲突返回策略
- 给出阶段化重构目标与边界

## Out of Scope / Non-goals

- 第一阶段不引入数据库
- 不做跨实例并发写冲突的自动合并
- 不做所有 workspace 文件的对象级按需读取
- 不展开 Redis 持久化、灾备、HA 设计
- 不直接实现代码改造

## Decision Boundaries

- 第一阶段基础设施限定为 `Redis + S3`
- Redis 负责：
  - 在线 session
  - 分布式锁
  - 幂等/请求去重辅助状态
- S3 负责：
  - workspace 文件
  - agent 配置文件
  - 长期归档内容
- 同一 `user_id + agent_name + session_id` 的并发写请求：
  - 不排队
  - 不自动合并
  - 第二个请求快速失败并提示稍后重试
- 第一阶段允许保留请求级临时工作目录来复用现有 `AgentLoop`

## Constraints

- 当前 cloud 实现是 brownfield，不是 greenfield
- 当前 `AgentLoop` / `SessionManager` / `SkillsLoader` 仍依赖本地文件系统语义
- 用户已经明确生产约束：
  - 多实例
  - 无状态
  - 无会话粘性
- 第一阶段不能引入数据库

## Testable Acceptance Criteria

- 方案明确指出实例本地只保留请求级临时目录，不承担跨请求状态
- 方案给出 Redis 与 S3 的职责边界
- 方案定义同一会话并发写请求的默认行为为快速失败
- 方案说明如何从当前 `nanobot.cloud` 演进，而不是另起一套无关系统
- 方案包含至少一个阶段化迁移路径（当前实现 -> 第一阶段无状态多实例）

## Assumptions Exposed + Resolutions

- 假设 1：高频状态是否仍可继续放 S3
  - 结论：否，高频在线状态迁到 Redis
- 假设 2：第一阶段是否要引入数据库
  - 结论：否，先不引入
- 假设 3：并发写冲突是否要自动合并
  - 结论：否，锁冲突快速失败
- 假设 4：第一阶段是否必须做到纯对象级按需读取
  - 结论：否，可以保留请求级临时工作目录

## Pressure-Pass Findings

- 服务端等待锁释放虽然用户体验更好，但与无状态多实例的一阶段目标冲突，故被放弃。
- 保留请求级临时工作目录被确认是可接受折中，用于降低对现有 `AgentLoop` 的侵入式改造。

## Brownfield Evidence vs Inference

### Repository-grounded facts

- `nanobot/cloud/runtime.py` 当前会把用户 workspace 下载到本地缓存，再创建 runtime 副本运行
- `docs/CLOUD.md` 当前定义了 platform-config 本地路径和 S3-backed user workspace
- 当前 session 仍通过 workspace 文件体系持久化

### Inferences to validate during planning

- 第一阶段应把 session 主存储从 workspace 文件迁移到 Redis
- 工作区配置索引在没有 DB 的前提下，仍可继续放 S3 文件，但要避免实例本地持久缓存承担主语义
- 需要显式定义 Redis key 设计、锁 TTL、冲突错误码与重试建议

## Technical Context Findings

- [nanobot/cloud/runtime.py](/home/fweil/gitprojects/nanobot/nanobot/cloud/runtime.py)
- [nanobot/cloud/server.py](/home/fweil/gitprojects/nanobot/nanobot/cloud/server.py)
- [nanobot/cloud/storage.py](/home/fweil/gitprojects/nanobot/nanobot/cloud/storage.py)
- [docs/CLOUD.md](/home/fweil/gitprojects/nanobot/docs/CLOUD.md)
- [test_cloud_api.py](/home/fweil/gitprojects/nanobot/test_cloud_api.py)

## Recommended Execution Bridge

### Recommended: `$ralplan`

- Why: 现在边界足够清楚，但真正的重构方案还需要产出阶段化架构、Redis key/lock/session 设计、S3 对象职责、临时工作目录生命周期，以及从当前实现迁移的计划和 test shape。
- Suggested invocation: `$plan --consensus --direct .omx/specs/deep-interview-cloud-stateless-multi-instance.md`

## Condensed Transcript

1. 高频在线状态走 Redis
2. 第一阶段不引入数据库
3. 不做自动合并、不做全对象级按需读取、不做 Redis 灾备设计
4. 并发写请求默认快速失败，不做服务端排队
