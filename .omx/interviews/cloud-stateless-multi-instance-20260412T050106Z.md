# Deep Interview Transcript

- Interview id: `cloud-stateless-multi-instance-20260412T050106Z`
- Profile: `standard`
- Context type: `brownfield`
- Final ambiguity: `8.85%`
- Threshold: `20%`
- Context snapshot: `.omx/context/cloud-stateless-multi-instance-20260412T050106Z.md`

## Summary

本次需求不是直接实现，而是为现有 `nanobot.cloud` 产出一份面向“多实例、无状态、无会话粘性”的重构方案。方案第一阶段明确限定在 `Redis + S3`，不引入数据库。

## Round Transcript

### Round 1

- Target: `decision-boundaries`
- Q: 高频会话状态最终落在哪里？
- A: `Redis` 做在线 session / 锁 / 幂等，高价值长期归档再落 S3。
- Impact: 在线状态层与长期文件层分离。

### Round 2

- Target: `decision-boundaries`
- Q: 数据库在第一阶段的定位是什么？
- A: 第一阶段先不引入数据库，只用 `Redis + S3`。
- Impact: 方案必须在没有 DB 的前提下完成元数据与会话分层。

### Round 3

- Target: `non-goals`
- Q: 第一阶段最明确不做什么？
- A: 不做跨实例并发写自动合并；不做所有 workspace 文件的对象级按需读取；不做 Redis 持久化/灾备设计。
- Impact: 范围收缩为“Redis 锁 + Redis session + S3 workspace + 请求级临时工作目录”。

### Round 4

- Target: `decision-boundaries`
- Q: 同一用户/agent/session 的两个写请求同时打到不同实例时，锁行为是什么？
- A: 第二个请求快速失败，返回冲突/稍后重试。
- Impact: 第一阶段优先追求无状态稳定性而非服务端排队体验。

## Pressure-Pass Findings

- 对“无状态多实例”做了实现边界压力测试，确认不是“服务端等待锁释放”，而是“快速失败 + 客户端重试”。
- 对基础设施范围做了约束压力测试，确认第一阶段不引入数据库。

## Residual Risk

- 第一阶段仍保留请求级临时工作目录，意味着 `AgentLoop` 仍然依赖本地文件系统语义，后续阶段若要做到更细粒度按需下载，需要更深层 runtime 改造。
- 不做自动合并意味着客户端、网关或上层任务编排必须能处理 `409/429` 风格的冲突重试。
