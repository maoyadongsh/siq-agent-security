# CL-04-BINDING-EXECUTION-RECHECK 交付记录：部署执行前绑定身份复验与漂移拒绝

日期：2026-09-26。范围：仅“部署准备结果生成后、真正执行前绑定被吊销或来源身份漂移，旧准备结果仍可能被使用”的核对与最小修复。未提交、未部署，待主开发者复核。本记录不声明 CL-04、CL-05 或整体项目完成。

## 1. 修改与新增文件

修改（白名单内）：

- `apps/control-api/app/binding_identity.py`
  - 新增 `SNAPSHOT_FIELDS`（status、environment_id、asset_id、agent_instance_id、backend、backend_target_id）。
  - 新增 `snapshot_binding_identity(binding)`：准备阶段校验通过后的标量副本（普通 dict，不随 ORM 对象漂移）。
  - 新增 `require_binding_identity_unchanged(session, snapshot, tenant_id)`：执行前持久状态复验（fail-closed）。
  - 原 `require_binding_source_identity` 语义不变，与复验共用 `_source_identity_missing` 查询助手（同一事实源）。
- `apps/control-api/app/routers/policies.py`（仅 PreparedDeployment 快照字段与 prepare/execute 附近最小接入）
  - `PreparedDeployment` 新增内部字段 `binding_snapshot: dict`（`app/routers/policies.py:424`）。
  - `prepare_deployment` 返回时填入快照（`app/routers/policies.py:571-575`）。
  - `execute_deployment` 在 openshell target-authority 复验之后、任何副作用之前调用复验（`app/routers/policies.py:600-605`）。
  - 既有 36 行未提交修改（prepare 来源身份检查、execute target authority 复验、rollback 复验）全部保留，未重写其他策略/审批/回滚逻辑。
- `packages/contracts/enterprise-runtime-binding-identity.v1.md`
  - 追加“执行前复验”实现保证段（wire 不变）：检查位置、比对字段、错误语义、残余竞态声明。无 API 字段/版本/状态枚举变化。
- `apps/control-api/app/tests/test_binding_source_identity.py`：未改动（既有 9 用例全部保留并通过）。

新增：

- `apps/control-api/app/tests/test_binding_execution_recheck.py`（19 用例）。
- `docs/development/enterprise-binding-execution-recheck-handoff.md`（本文件）。

未触碰：models.py、迁移、共享数据库配置、身份模块、审计/outbox 实现、适配器、后端路由定义、前端、Edge、Connector、安装器、依赖、锁文件、公共台账，以及 Qwen/GLM/主开发者负责的在途文件。

## 2. 准备→探测→执行各阶段检查位置（修复后）

`prepare_deployment`（`app/routers/policies.py:435-575`）：CR 定位+行锁（`with_for_update().execution_options(populate_existing=True)`）→ 环境/策略定位 → 权限（policy:manage 等）→ 既有预约排斥 → CR 状态 → 环境 enforce → **绑定 active、绑定环境一致 → `require_binding_source_identity`（实例/资产/环境按验证租户核对）** → 隔离门禁 → selector 强绑定 → 后端/能力检查 → openshell：`probe()` + `require_target_authority` + 编译/plan → 返回时记录 `binding_snapshot`。

`execute_deployment`（`app/routers/policies.py:577-`）：openshell 路径先重新 `probe()`（最后一次外部只读探测）→ `require_target_authority` 并与准备时 authority 比对（`deployment_target_authority_changed`）→ **本次新增：`require_binding_identity_unchanged` 持久状态复验** → Deployment 行 → `apply_dynamic`（真实外部写入）→ verify/审计/outbox；fake 路径复验同样在 EdgeTask `publish_policy` 创建之前。

所有 `execute_deployment` 调用方共享该边界：`create_deployment`（policies.py:432）、`submit_deployment`（deployment_preview.py:247）、`_execute_new_reservation`（deployment_submission.py:258）、批量 `execute_batch`（batch_execution.py:54，经 `_execute_new_reservation`）。

## 3. 风险核对结论（已复现 / 原机制已阻止 / 未验证）

复现方法：新测试在**未修复代码**上运行，漂移全部经独立会话（`session_scope()`，独立连接）真实提交，不是内存对象自证。结果 **17 failed / 2 passed**（2 个无漂移正例通过），即缺口全部复现：

| 场景（准备后、副作用前提交漂移） | 修复前（复现） | 修复后 |
| --- | --- | --- |
| 绑定 active→revoked（fake） | 201 sent；Deployment/EdgeTask/AuditEvent/OutboxEvent 各 +1（publish_policy 任务与成功审计落库） | 409 binding_revoked；四表计数零变化 |
| 绑定 revoked（openshell） | 201 effective；`runner.set_calls == 1`（apply_dynamic 真实调用） | 409 binding_revoked；set_calls == 0；零落库 |
| revoked 发生在执行期 probe 返回前（openshell） | 201 effective；set_calls == 1 | 409 binding_revoked；set_calls == 0 |
| 绑定引用漂移 ×6（target/environment/asset/instance/backend/tenant） | 各 201 sent | 各 409 binding_source_identity_changed；零落库 |
| 实例来源漂移 ×5（environment/unknown_environment/asset/instance_tenant/asset_tenant） | 各 201 sent | 各 409 binding_source_identity_changed；零落库 |
| preview digest 仍匹配时的 submit（digest 由同一份陈旧 ORM 状态计算，无法发现漂移） | 201 sent | 409 binding_revoked；零落库 |
| 持久预约重 prepare 之后、execute 副作用之前 revoked | 201 recorded；EdgeTask 创建 | 502 deployment_submission_unconfirmed；预约保留 pending；无 EdgeTask；重放只读 |
| 批量首项 execute 前 revoked | recorded（两项 sent） | unconfirmed；首项 pending、后续项 failed 且 backend_mutated=False；零 EdgeTask |

关键机制证据（同一测试内）：漂移提交后，请求会话中的 `prepared.binding.status` 仍读为 `active`（ORM identity map 旧值），而独立会话读到 `revoked`——既有的 execute 期 target-authority 复验使用的是这份旧 ORM 属性，因此无法发现绑定侧漂移，证明“只在 execute 复用旧对象做检查”不等于读取了持久状态。

原机制已阻止（未重复重构，仅回归确认）：

- 漂移发生在**预约提交前**或**重 prepare 前**：`_execute_new_reservation` 先 `expire_all()` 再重跑 `_prepare`，既有用例 `test_binding_revoked_during_reservation_is_rechecked_before_execute` 覆盖（deployment_submission 回归通过）。
- 预览→提交之间的漂移：`preview_digest` 对 `_snapshot` 全量内容做摘要比对（`deployment_preview_changed`，既有用例覆盖）。
- authority 文件本身变化/失效：`deployment_target_authority_changed|unverified`（既有用例覆盖）。
- 回滚：既有 `authorize_rollback` 已 `expire_all` 后重查 live binding + 来源身份 + target authority + 端点指纹比对（未触碰）。

未验证（如实声明）：

- 真实 PostgreSQL 下的并发/隔离级别行为：本验证全部在 SQLite 合成夹具完成，不以 SQLite 冒充 PostgreSQL 并发证明。列级重读在请求事务内读到其他事务已提交数据依赖数据库隔离级别；PostgreSQL READ COMMITTED 下每条语句读最新已提交快照，语义与本设计一致，但未经真实 PostgreSQL 复跑。
- 真实 OpenShell 写入：全部使用 StatefulRunner/模拟适配器。
- 复验之后到外部写入之间的残余竞态窗口（见 §8）。

## 4. 复验设计（快照、持久读、错误）

- **标量快照**：`prepare_deployment` 返回前取 `snapshot_binding_identity(binding)`——绑定 id + 六个标量字段的普通 dict。旧值来源是准备阶段校验通过的那一刻，不是执行期的可变 ORM 对象。
- **持久状态重读**：`require_binding_identity_unchanged` 用列级 `select(...).mappings()` 按 `id + tenant_id` 重读；列级查询不经 ORM identity map；tenant 谓词只来自验证身份（`identity.tenant_id`），PreparedDeployment 中的对象不作为租户权威。
- **判定顺序**：行缺失（含跨租户不可定位）→ 409 `binding_source_identity_changed`；当前状态非 active → 409 `binding_revoked`；任一标量字段与快照不符 → 409 `binding_source_identity_changed`；再按当前持久值重跑实例/资产/环境来源核对。错误为既有固定脱敏语义（与 prepare 期同一组码），不含目标详情、其他租户对象、attestation 或秘密。
- **失败关闭边界**：拒绝时不采用新 target、不重编译、不更新绑定掩盖漂移、不恢复 revoked、不重试外部写入；复验只读+拒绝。
- **检查位置**：openshell 路径位于最后一次外部只读探测（fresh `probe()` + authority 比对）之后、`apply_dynamic` 之前——`test_binding_revoked_during_execute_probe_is_rejected_before_apply` 证明若复验只放在 execute 入口（probe 之前），probe 期间提交的漂移会被错过。fake 任务通道同样被该复验覆盖，不能绕过。

## 5. 预约、审计、审批、隔离与幂等语义保留

- 复验在副作用之前拒绝：直接部署路径不留 Deployment 行、EdgeTask、成功审计或 outbox（各用例断言四表计数零变化）。
- 持久预约路径：复验拒绝发生在 `execute_deployment` 内，按既有调用方约定保守处理为未知——预约行不释放、Deployment 保持 `pending`（不标 effective、不标 failed）、`deployment.reserve` 审计保留，重放同键只返回原结果且不再进入执行（`calls == [1]`）。这是既有“执行结果未知不盲改状态”的约定，本次未为改善文案破坏它；如实记录：同一拒绝在重 prepare 阶段表现为 `needs_attention`，在 execute 阶段表现为 `unconfirmed`。
- 批量路径：漂移项保持 pending/未知，后续未开始项由既有 `_stop_unstarted` 标记 `backend_mutated=False` 的 failed，重放整个批次只读。
- 审批（职责分离、high_risk 降级）、selector 强绑定、隔离门禁、target authority、预览摘要、revision CAS、独立读回验证均未改动；新复验是叠加门禁，不替代任何既有检查。
- 审计不可用失败关闭机制未触碰（`test_reservation_audit_failure_never_calls_execute` 回归通过）。
- 未新增自动补偿、自动回滚或后台重试；未删除/释放/重新利用任何已有预约。

## 6. 验证命令与结果

环境：`apps/control-api`，`uv run --no-sync pytest -o addopts=''`，SQLite 合成夹具 + 模拟适配器（L1/L2 级证据，非生产证明）。未安装依赖、未联网、未运行生产数据库。

修复前复现（同一新测试文件）：**17 failed / 2 passed**，失败输出记录副作用确已发生（apply_dynamic `set_calls == 1`；四表计数各 +1；预约/批量 recorded）。

修复后：

1. `uv run --no-sync pytest -o addopts='' -q app/tests/test_binding_execution_recheck.py app/tests/test_binding_source_identity.py --tb=short` → **28 passed**。
2. `... app/tests/test_runtime_binding.py app/tests/test_target_authority.py` → **44 passed**。
3. `... app/tests/test_deployment_preview.py app/tests/test_deployment_submission.py app/tests/test_batch_execution.py app/tests/test_batch_execute_api.py app/tests/test_batch_reservation.py app/tests/test_deployment_impact.py app/tests/test_policy_flow.py app/tests/test_deployment_verify.py` → **88 passed**。
4. `uv run --no-sync ruff check app/binding_identity.py app/routers/policies.py app/tests/test_binding_execution_recheck.py` → All checks passed。
5. `git diff --check` → 通过；新增未跟踪文件尾随空白检查 → 无。

未运行：control-api 全量、Go/前端/浏览器、真实 PostgreSQL、真实 OpenShell（均按任务边界排除）。

**既有顺序敏感脆弱性（先于本次改动，与本次无关）**：`test_policy_flow.py::test_deployment_requires_verification_evidence` 在特定多文件组合（如 runtime_binding + target_authority + deployment_preview + deployment_submission + batch_execution + test_policy_flow）下失败（StopIteration）。机制：会话级共享 SQLite 中 env_a 累积 ≥10 条未回执的 pending publish_policy 任务，`GET /edge/v1/tasks` 按 created_at 升序只返回最旧 10 条，新任务不可见。已用同一组合在未修复原始代码上复跑确认同样失败（1 failed / 100 passed），证明与本次修改无关；未替任何并行负责人修该测试，按调用链拆成上述确定性分组回归。新测试文件自身只在 env_a 留下 1 条 pending 任务（唯一正例），与 test_policy_flow 合跑 43 项通过。

## 7. 保证边界（明确不宣称）

- 仅保证：对复验时已经能够从数据库观察到的绑定吊销或身份漂移，旧准备结果被拒绝，且拒绝前无任何外部写入或任务/成功审计落库。
- 不宣称：数据库与外部 OpenShell 写入构成原子事务；消除了全部 TOCTOU。复验之后、`apply_dynamic`/任务创建之前仍存在残余窗口（另一事务可在此期间提交漂移）；消除它需要新的锁/租约协议（如绑定行锁贯穿 prepare→execute 或执行租约），超出本任务范围，仅在此登记。
- 不宣称：建立了跨服务锁或租约；证明了真实设备、Skill 实际加载、沙箱独占或共享归属；完成完整运行时安全闭环（仍属 CL-04/CL-05 后续）。
- SQLite 合成证据不冒充 PostgreSQL 并发证明；目标 authority 文件语义未变。

## 8. 状态

CL-04-BINDING-EXECUTION-RECHECK 子任务：复现完成、最小修复完成、定向回归完成。未提交、未部署，待主开发者复核。CL-04、CL-05 及整体项目不因此关闭。

## 9. 主开发者复核（2026-09-26）

核对列级重读、快照字段、execute 期 probe 后的检查位置及单项/批量持久预约调用链，未发现本轮需要修改的业务代码缺陷。复验拒绝前无 apply_dynamic 或新 publish_policy 任务；单项预约与批量重放均由已有持久记录阻止再次执行。交付聊天摘要中的“预约释放”是错误表述，实际应为“预约不释放”，本文件第 5 节及测试已正确断言。

修正合同保证范围：复验发生在 execute_deployment 内新增行和执行动作之前，不能说整个请求尚无任何副作用；持久预约、pending Deployment 与 reserve 审计可能已提交，拒绝时应保留。执行期 probe 是该函数的检查位置，不宣称适配器内部没有后续读取。普通 dict 是与 ORM 分离的标量副本，不是语言层面的不可变对象。仅修改合同表述，本轮未修改 Kimi 的业务代码或测试，也未触其他开发线。

实际复跑（工作目录 apps/control-api）：

```bash
uv run --no-sync pytest -o addopts='' -q app/tests/test_binding_execution_recheck.py app/tests/test_binding_source_identity.py app/tests/test_deployment_submission.py app/tests/test_batch_execution.py --tb=short
uv run --no-sync pytest -o addopts='' -q app/tests/test_runtime_binding.py app/tests/test_target_authority.py --tb=short
uv run --no-sync ruff check app/binding_identity.py app/routers/policies.py app/tests/test_binding_execution_recheck.py
```

结果分别为 **44 passed、44 passed**，合计 88 项定向验证；仅既有 Starlette/httpx 弃用提示。Ruff、git diff --check 与新测试/交接文件尾随空白检查通过。未复跑全仓或顺序敏感 policy_flow 组合，不将此结果宣称为全量门禁通过。

本子任务按已声明的“数据库可观察漂移拒绝”范围验收通过。SQLite 合成会话与模拟适配器不证明 PostgreSQL 并发、真实 OpenShell 或复验之后的原子执行。既有残余窗口和 pending 结果语义仍保留，不关闭 CL-04/CL-05。未提交、未部署。
