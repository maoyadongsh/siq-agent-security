# 绑定失效联动面 v1

R04 增量。对应 ENT-013、014。与 [enterprise-binding-evidence-readiness/v2](enterprise-binding-evidence-readiness.v2.md)、[enterprise-evidence-topology/v1](enterprise-evidence-topology.v1.md) 同族：**内部只读投影，不是 HTTP 接口，不是吊销执行器，不是执行授权**。本版本不新增端点、不新增迁移、不改任何既有响应、不做级联修改。

## 解决的问题

仓储已有绑定复验（`app/binding_identity.py::require_binding_identity_unchanged`）与绑定吊销（`APP.POST /api/v1/runtime-bindings/{binding_id}/revoke`），但**没有任何投影回答"这个绑定被谁引用、失效后哪条既有路径会被拒绝"**。吊销端点自身不做依赖检查：它只把状态置为 `revoked` 并记审计，级联拒绝只在使用点（预览/执行侧的绑定复验）发生。历史风险：把"历史部署记录存在"当作"当前仍有运行占用"，或把"查不到第二条绑定"当作独占证据。

## 只读边界

`app/binding_invalidation_surface.py::project_binding_invalidation_surface(session, identity, binding_id, draft_scan_limit=200)`。只做租户限定的 `SELECT`；不写库、不产生审计/outbox/任务、**不吊销任何行**、**不重放/重试/标记失败**、不发起外部探测、不扫描宿主。`tenant_id` 只取自服务端验证身份；绑定缺失或属于其它租户返回与"不存在"完全相同的结构，不构成跨租户存在性判别。不复制第二套绑定判定：吊销即拒绝的语义直接取自既有复验的固定拒绝码 `binding_revoked`；草稿解析复用 `BatchDeploymentPreview`。

## 两类引用，覆盖范围不同

| 引用 | 来源 | 覆盖 |
| --- | --- | --- |
| **硬引用** | `Deployment.runtime_binding_id`（外键） | 该租户全部**已预留**的部署记录，按状态计数 |
| **软引用** | `DeploymentBatchDraft.preview.items[].binding_id`（JSON） | **仅调用方自身身份**的**存活**草稿 |

软引用之所以窄：草稿按 `actor_id` + `actor_type` 归属（与 `_owned_draft` 同一规则），读取其它身份的草稿既是越权也不在本层职责内，因此 `other_actor_live_batch_drafts` 恒为 `not_determinable`，报 `draft_ownership_is_actor_scoped` 与 `other_actor_live_drafts_not_enumerable`——**不声称全租户覆盖**。已过期草稿不在扫描范围内，报 `expired_drafts_outside_scan_scope`：`app/batch_execution.py` 在起始每项前检查截止时间，过期草稿**不可能再启动新项**（已预留项由硬引用侧覆盖）。

## 状态词表（固定五值，无"部分覆盖"）

| 值 | 含义 |
| --- | --- |
| `dependency_absent` | 记录范围内没有任何引用 |
| `dependency_recorded` | 有记录引用（当前仅用于历史部署记录） |
| `blocked_if_revoked` | 绑定当前 `active`；一旦吊销，该路径会在使用点被拒绝 |
| `blocked_now` | 绑定当前已 `revoked`，该路径**此刻已被拒绝** |
| `not_determinable` | 无法由记录判定（跨租户/不存在、扫描截断、预览不可读、其它身份草稿、运行占用无来源） |

**扫不完不等于没引用**：`draft_scan_limit`（默认 200）之内的存活草稿若已被扫满，或存在无法解析的预览，结论一律降为 `not_determinable` 并附 `draft_scan_truncated` / `draft_preview_unreadable`，**不得**声明 `dependency_absent`。扫描元数据 `{scanned, limit, truncated}` 一并返回；损坏草稿的 id 单列在 `unreadable_draft_ids`。

## 吊销时固定结论集（`effect_if_revoked`）

只列既有代码路径**可判定**的拒绝语义，不预测任何效果：

- `new_preview_or_execute_on_this_binding_rejected: "binding_revoked"`（复验固定拒绝码）
- `unreserved_draft_reserve_rejected: "binding_revoked"`
- `existing_deployment_records_are_not_modified: true`
- `existing_effects_are_not_reverted: true`（**吊销不是回滚**）
- `already_expired_drafts_cannot_start_new_items: true`
- `binding_state_currently`

## 刻意不改变的事实

`execution_confirmation_supported` 恒为 `False`（与 `deployment_impact.py:49`、`binding_evidence_readiness.py:190` 同一保留语义）；`shared_runtime_occupants` 恒为 `"unknown"`，`coverage` 恒为 `"recorded_dependencies_only"`。本投影**不**新增锁、租约或独占性标准，**不**把"查不到第二条绑定"解释为独占（D-3：共享独占标准未定，保持 `unknown` 不猜）。

## 不得由此投影推导（固定码，不随输入变化）

`recorded_dependency_is_not_runtime_occupancy`、`revocation_does_not_rollback_or_replay_history`、`no_recorded_dependency_is_not_no_runtime_occupancy`、`shared_runtime_occupants_remains_unknown`、`other_actor_draft_coverage_is_not_established`、`scan_scope_is_persistent_records_only`；组级另有 `deployment_record_is_not_current_runtime_state`、`revocation_is_not_a_deployment_rollback`、`draft_reference_is_not_a_reservation`、`own_live_draft_scan_is_not_full_tenant_coverage`、`expired_draft_is_not_scanned`。

## 实现与状态

`app/binding_invalidation_surface.py`；隔离验证 `app/tests/test_binding_invalidation_surface.py`（7 用例：只读且零写入、跨租户与不存在不可区分、历史部署记录不当作当前状态、存活草稿在吊销前后由 `blocked_if_revoked` 转为 `blocked_now`、其它身份与过期草稿不成为"无引用"、截断与不可读降为无法判定、入参与验证身份边界）。同组回归 94 passed，ruff 通过。

**源码级 + 隔离验证级**（合成绑定/部署行/草稿行，独立 SQLite）。**未接线**：内部只读投影，无 HTTP 路由；`binding_evidence_readiness.assess_binding_evidence` 与本模块均**无生产调用方**。**不证明**真实运行占用、真实沙箱 revision、真实共享影响，也不替代真实吊销行为验收——归 R09 资源门槛。
