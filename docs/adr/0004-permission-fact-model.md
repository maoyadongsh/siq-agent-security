# ADR-004：统一权限事实模型（含委托维度）

- 状态：**已采纳（暂行）**
- 日期：2026-08-13

## 决策

- 权限以 Permission Fact 表达（subject/domain/action/resource/effect/conditions/state/authority/revision/evidence_ids），域间不合并（设计文档 §12.1）；
- **delegated_user 维度**：智能体代用户运行时，有效数据范围 = Agent 权限 ∩ 调用用户数据范围；来源优先 SIQ IAM `/auth/delegated-token`（`act` claim、purpose、TTL≤300s、逐次审计），不信任 Agent 自报身份（对应评审 P0-1）；
- 域内重叠资源模式输出 `overlap_conflicts`，不静默取任意一条（§12.4）；
- 模型权限域必须输出 agent×model 组合事实；当前 SIQ Gateway 无此组合校验 → 状态为 `unknown` 并触发规则告警。

## 后果

- 正：有效权限视图可信、可解释。
- 负：Resolver 实现成本高于扁平字符串权限表。
