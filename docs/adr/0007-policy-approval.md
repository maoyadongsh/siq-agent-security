# ADR-007：策略审批、发布和回滚（含 enforcement_mode 与 Break-glass）

- 状态：**已采纳（暂行）**
- 日期：2026-08-13

## 决策

- 策略生命周期 `draft→validated→proposed→approved→deploying→effective`，回滚同权审计；
- **enforcement_mode 渐进档位** `audit_only→warn→block`，只允许升级路径，降级必须走新变更审批；与 siq-platform 架构文档 §11（Observe→Canary→A/B→Enforced→Default）在 Phase 0 对齐评审后统一字段语义；
- 职责分离：提出者不能是唯一批准者（含 `approval_policy=break_glass`——Break-glass 不豁免 SoD，仅允许跨人紧急批准；记录短期授权与事后复核标记，`post_review_due` 状态待 Phase 3 落地）；
- Break-glass 变更单发起需独立权限点 `change:break_glass`（授予 `security_admin` 角色，§19.2），与 `change:propose`/`change:approve` 分离；普通 proposer 自选 break_glass 直接 403；
- 幂等键：change-request 以 `idempotency_key` 唯一；
- 未批准不可部署；部署回执必须携带可机器校验证据（`verification` 字段强制于 API 层）；
- 静态校验：selector 必填、secret 只允许引用（ref+purpose）——明文即 draft 并显式列出错误（`unsupported_by_backend`）。

## 后果

- 正：已实现并有负向测试（SoD 409、未批准 409、幂等复用、回滚）。
- 负：quorum 多批准人模型待评审（开发计划决策 #14）。
