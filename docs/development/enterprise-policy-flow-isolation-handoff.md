# CL-01-POLICY-FLOW-ISOLATION 交付：部署回执测试的跨用例任务污染修复

日期：2026-09-26
修改人：后端测试工程师（Claude Code 会话）
状态：**未提交、未部署，待主开发者复核**。本交付只声明 CL-01-POLICY-FLOW-ISOLATION（测试闸门修复）完成，**不**声明 CL-01 全部完成或生产部署可用。

---

## 一、原始失败的独立复现（命令与结果）

按 recheck 交接文档（enterprise-binding-execution-recheck-handoff.md §6）记载的已知组合，在本会话独立复跑（未修复的原始代码上，运行于修复改动之前）：

```bash
cd /home/maoyd/siq/siq-agent-security/apps/control-api
uv run --no-sync pytest -o addopts='' -q \
  app/tests/test_runtime_binding.py app/tests/test_target_authority.py \
  app/tests/test_deployment_preview.py app/tests/test_deployment_submission.py \
  app/tests/test_batch_execution.py app/tests/test_policy_flow.py --tb=short
```

结果（存档：`/tmp/siq-cl01-policy-flow-isolation/repro-combo-before-fix.txt`）：

```text
app/tests/test_policy_flow.py:191: in test_deployment_requires_verification_evidence
    task = next(
E   StopIteration
FAILED app/tests/test_policy_flow.py::test_deployment_requires_verification_evidence
1 failed, 100 passed, 1 warning in 10.22s
```

**定性**：失败点是 `next(...)` 在任务领取响应里找不到目标任务（StopIteration），**不是**业务接口拒绝部署。依据：`_approved_deployment` 中 `POST /api/v1/deployments` 先于失败行执行且未抛错（修复后已补状态码断言进一步固化该前提）；结合 Edge 路由实现（`apps/control-api/app/routers/environments.py:419` `edge_fetch_tasks`：候选按 `environment_id == edge.environment_id` 过滤、`order_by(created_at).limit(10)` 升序取最旧 10 条），机制确为会话级共享环境上跨文件累积的未回执 pending publish_policy 任务挤占领取批次，导致新部署任务不在返回集中。两类失败未混淆。

## 二、文件内受影响用例清单（test_policy_flow.py）

共享污染双向存在：其他文件向会话级 `env_a` 沉积任务（挤占本文件领取批次）；本文件用例也向 `env_a` 沉积任务（反向污染其他文件的领取）。本文件内所有使用会话级 `env_a` 的用例（修复后全部改用用例级独立环境）：

| 用例 | 是否领取任务 + `next(...)` | 修复前固定设备身份 |
| --- | --- | --- |
| test_deployment_requires_verification_evidence | 是（直接复现点） | edge-verify-1 |
| test_deployment_effective_with_verification | 是 | edge-verify-2 |
| test_edge_publish_policy_receipt_constant_fail_closed | 是 | edge-const-1 |
| test_deployment_compiles_with_fake_backend | 是 | edge-compile-1 |
| test_deployment_requires_approval | 否（但向共享环境沉积任务） | — |
| test_deployment_openshell_cli_closed_loop | 否（同步闭环，但绑定/部署指向共享环境） | — |
| test_deployment_does_not_invent_conflicting_deny_probe | 同上 | — |
| test_post_apply_verification_failure_preserves_safe_rollback_binding | 同上 | — |
| test_deployment_openshell_cli_rejects_non_block_mode_422 | 同上 | — |
| test_deployment_openshell_apply_failure_fails_closed | 同上 | — |
| test_rollback_invokes_bound_backend_operation | 同上 | — |
| test_rollback_rejects_revoked_runtime_binding | 同上 | — |
| test_break_glass_cross_person_emergency_approval | 否（沉积任务） | — |
| test_break_glass_review_due_preserves_business_status | 否（沉积任务） | — |

辅助函数 `_approved_deployment`、`_edge_headers` 同步改造，保证绑定、注册、部署、领取全部落在同一用例级环境上（不是改名留下的共享引用）。

## 三、独立环境与设备身份的建立方式

1. **环境**：文件内新增函数级 fixture `env_iso`（conftest.py 与共享 fixture 未动）：经真实 API `POST /api/v1/environments` 创建，名称 `policy-flow-iso-<uuid12>` 保证跨运行不冲突，`mode: "enforce"` 显式指定，`env_type: "host"` 与原 env_a 一致，租户仍为测试租户 tnt-A（tenant_a 头）。不读取任何生产配置。
2. **设备身份**：`_edge_headers` 内将语义前缀（如 `edge-verify-1`）追加 uuid 后缀使用。依据：`register_edge` 路由对 `device_identity` 全局唯一，重复注册返回 409 `device_identity_conflict`（environments.py 预检 + IntegrityError 双保护）；唯一化避免同会话内跨用例/跨文件冲突。密钥仍来自既有测试夹具 `edge_helpers.edge_public_key_pem`（sha256("siq-test-edge:<identity>") 派生的测试专用 Ed25519，非真实设备种子/私钥）。
3. **同一性**：env-enrollment、/edge/v1/register、部署、GET /edge/v1/tasks、回执全部使用该用例的 `env_iso` 与该用例注册的设备。

## 四、未绕过任务领取与回执安全验证的证据

- 领取路径原样：仍走真实 `GET /edge/v1/tasks`（Bearer device_secret + X-Edge-Identity 认证、原子 claim/lease），未从数据库直接挑任务、未 monkeypatch 任务列表、未提高 limit(10)、未向无关任务提交回执清队列、无循环领取/等待。
- 回执路径原样：仍走真实 `POST /edge/v1/tasks/{id}/receipt`；四条安全断言全部保留且逐条通过：
  - 无 verification 证据 → 部署 `failed` 不得 effective（不变量 #5）；
  - 常量语义：伪造成功回执仍 `failed` + `edge_publish_unsupported`（outbox 事件断言保留）；
  - 任务↔部署精确匹配（`payload.deployment_id == dep["id"]`）未放宽；
  - 租户/跨租户用例（test_policy_cross_tenant_404、test_list_endpoints_tenant_isolated）未改动，断言未放松。
- 上游可见性：按修复要求补齐状态码断言——`_approved_deployment` 部署 201、enrollment 200、register 200、领取 200，上游失败不再被 KeyError/StopIteration 掩盖。
- 用例数不变：文件内用例数与修复前一致（24 条），未新增测试模块、未改任何安全断言方向。

## 五、最小验证 A–D 实际结果

命令统一：`cd apps/control-api && uv run --no-sync pytest -o addopts='' -q <files> --tb=short`

| 验证 | 组合 | 结果 |
| --- | --- | --- |
| A 单文件 | test_policy_flow.py | **24 passed** |
| B 已知污染组合 | runtime_binding + target_authority + deployment_preview + deployment_submission + batch_execution + test_policy_flow（本文件最后） | **101 passed**（修复前同组合 1 failed / 100 passed） |
| C 顺序反转 | 同 B，但 test_policy_flow.py 放最前 | **101 passed** |
| D 集中回归（等价证据） | 未新增用例；改为对 C 组合运行后的隔离合成库做只读核查 | 见下 |

D 的只读核查（组合 C 运行后 SQLite 合成库，证据等级 L1/L2 合成环境）：共享 `dev-host-a`（tnt-A）在该组合中累积 9 条 pending publish_policy（来自其他 5 个文件），而本文件每个回执用例各自从专属 `policy-flow-iso-*` 环境领取并回执自己的任务（3 条 delivered，其余为各环境独立 pending），全部同租户 tnt-A——证明同租户他环境存在大量积压时，专属环境领取不受挤占，且本文件不再向共享环境沉积任务。未安装随机排序插件，未更新任何依赖。

## 六、修改范围、未运行项、遗留问题

**修改范围（全部在白名单内）**
- `apps/control-api/app/tests/test_policy_flow.py`：新增 `env_iso` fixture；env_a→env_iso 全量替换（仅本文件）；`_edge_headers` 设备身份唯一化 + enrollment/register 状态码断言；`_approved_deployment` 部署 201 断言；4 处领取响应 200 断言。未改任何断言方向、未重排文件、未做无关格式化。
- 本文档 `docs/development/enterprise-policy-flow-isolation-handoff.md`（新增，白名单允许）。
- 未触碰：conftest.py、共享 fixture、binding_helpers.py、edge_helpers.py、任何生产代码（含领取 count 与回执路由）、其他测试文件、models/schemas/DB 配置/依赖/锁文件、前端/Edge/Connector/安装器/公共台账；drift.py（DeepSeek）、审计前端（Qwen）、Edge（主开发者）均未触碰。

**检查**：`uv run --no-sync ruff check app/tests/test_policy_flow.py` 通过；`git diff --check` 干净；无尾随空白。

**未运行项 / 限制**
- 未跑全仓 pytest（按任务要求最小验证）；未跑 apps/web 构建、Go 模块测试（不在本任务范围）。
- 所有证据来自 SQLite 合成测试库 + TestClient（L1/L2 证据），不构成生产形状证明。
- 其他开发者在途未提交改动（adapters/openshell、routers/* 等）未纳入我的验证基线；若其后续改动影响部署/领取语义，需以主开发者复核时的全量回归为准。

**遗留问题**
- 其他测试文件（如 test_binding_execution_recheck.py 等）自身是否也需要同款隔离不在本任务白名单内，未处理；本文件已停止向共享环境沉积任务，反向污染已消除。
- 领取批次 limit(10) 与 created_at 升序策略是生产行为，本次原样保留；若未来需要跨页领取，属产品决策，非测试可改。

## 七、结论

CL-01-POLICY-FLOW-ISOLATION 的收口阻断已修复并经 A–D 最小验证：单文件 24/24，两种顺序组合各 101/101，原始 StopIteration 不再复现，任务领取与回执安全验证路径未绕过。**未提交、未推送、未部署，待主开发者复核。**

## 八、主开发者验收（2026-09-26）

结论：本次测试隔离子项通过定向验收，无需追加代码修改。文件内不再引用 `env_a`；函数级环境沿绑定、部署、设备注册、领取贯通；设备身份与测试公钥使用同一个随机化标识。未发现删除、跳过或放宽原有失败关闭、任务匹配和跨租户断言的情况。生产领取上限、领取条件与回执实现未因本次验收而改变。

独立执行第五节 B、C 的六文件组合（本文件分别最后、最前）：各 **101 passed**，分别耗时 10.16s、10.46s；均只有既有 Starlette/httpx 弃用警告。`uv run --no-sync ruff check app/tests/test_policy_flow.py` 与仓库 `git diff --check` 均通过。按最小验证原则，没有再重复单文件或执行全量测试。

证据口径澄清：

- 本次组合执行使用验收时当前工作树，包括相关在途产品代码，并不是隔离的 HEAD 发布快照；不能把第六节“未纳入验证基线”理解成测试没运行这些依赖。本子项不负责审阅、归属或冻结它们。
- `git diff HEAD` 还包含既有目标授权合成夹具等改动，不能把全部累计 diff 都归因于 GLM 的隔离任务；本次未还原或覆盖这些成果。
- 第五节 D 所述其他环境 9 条 pending 是交付者的只读核查记录，本次未独立重跑该核查；9 条本身也不证明超过 limit(10) 的边界。接受依据是已知失败组合在两种顺序下均通过，以及用例级环境与生产环境过滤条件的一致性，不宣称任意测试顺序或真实多设备压力均已验证。

验收仅追加此记录，未修改测试代码、公共夹具或生产代码。未提交、未推送、未部署；不代表 CL-01 整体或正式发行完成。
