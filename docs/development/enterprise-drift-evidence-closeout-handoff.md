# 漂移巡检异常证据与租户关联收口交接（CL-05-DRIFT-EVIDENCE-CLOSEOUT）

日期：2026-09-26
状态：子任务完成（**未提交、未推送、未部署，待主开发者复核**）
范围：`apps/control-api/app/drift.py` 的 `check_policy_drift` 证据核对与租户限定。
本轮仅声明 `CL-05-DRIFT-EVIDENCE-CLOSEOUT` 子任务完成；**不宣称 CL-05、完整漂移治理或整个项目完成**。

---

## 1. 实际修改 / 新增文件

| 文件 | 动作 | 说明 |
| --- | --- | --- |
| `apps/control-api/app/drift.py` | 修改（+184 / −33） | 只改 `check_policy_drift` 及其私有辅助函数；`DriftResult` 结构、`upsert_drift_findings`、返回 kind 枚举、API 字段均未改动 |
| `apps/control-api/app/tests/test_drift_evidence_boundaries.py` | 新增 | 58 项参数化边界/负向测试，复用真实 `check_policy_drift` 与真实端点 |
| `docs/development/enterprise-drift-evidence-closeout-handoff.md` | 新增 | 本文件 |

未修改任何其他文件（`deployment_verify.py`、`routers/inventory.py`、`routers/policies.py`、`binding_identity.py`、`models.py`、`schemas.py`、共享审计/权限/适配器、前端/Edge/Connector/安装器、依赖与台账均只读）。
`git status` 中 `docs/development/current.md` 与其他未跟踪文件为本任务开始前已存在的工作树状态（`current.md` mtime 00:13，早于本会话），未触碰。

新增辅助函数：`_usable_identifier`(:66)、`_receipt_revision`(:75)、`_readback_reason`(:96)、`_endpoint_set`(:111)、`_unreadable`(:138)；固定原因码 :43–47。

---

## 2. 类型、空值及网络规则语义的合同依据

| 证据 | 合同 / 事实源 | 本轮采用的语义 |
| --- | --- | --- |
| `Deployment.target` | `models.py` `String(128)` | 读回 target 必须与本部署 target **完全一致**，否则该读回不是本部署的"当前有效规则" |
| `PolicySnapshot.target` / `.revision` | `contracts.py:133-151`（`str` / `str`） | 非 str、空串、纯空白、超 128 字符 → 读回结构不符合合同，按不可用证据（fail-closed） |
| `DeploymentReceipt.backend_revision` | `contracts.py:194-204`（`str`，无默认）；`schemas.py:121` Edge 侧 `max_length=128` | 回执存在即须给出可核对 revision；非 str / 空 / 空白 / 超限 / 显式异常 `target` → 不可核对 |
| `Deployment.receipt is NULL` | `Deployment.receipt` 可空（`models.py:533`） | 沿用既有语义：无回执只跳过 revision 维度，其余维度继续核对 |
| `DesiredPolicy.network` | `schemas.py:476`（`list` 可空） | `None` = 未声明网络（沿用既有"无期望 allow 规则"比较模型）；`[]` = 合法空规则集；其他容器 → 不可用证据 |
| `PolicySnapshot.network` | `contracts.py:147` `list[dict[str, Any]]` | 合同无 null：非列表容器 / null / 非对象行 / endpoint 非非空 str → 不可用证据，**不偷偷过滤成空列表** |
| 网络规则行字段 | `policy_safety.validate_network_rules`（生产者：`policy_compiler`）、`gateway_network_to_rules`（读回生产者） | 只做最小结构校验（对象、endpoint 非空 str、effect 若出现必须为 str）；不新增规则 schema、不校验 `binary_paths`/`rule_name`/L7 限制字段，保留 `effect != "deny"` 既有比较模型 |
| revision 取值宽松性 | `policy_safety._REVISION_RE = [1-9][0-9]*\Z` 仅用于 CLI 解析与 `apply_dynamic`；`fake_backend.py:127` 合法使用字符串 `"0"` | **未**在本模块新增正整数/纯数字限制；`"0"` 合法可用，`7`（int）不可用 |
| 错误参考脱敏 | `safe_errors.error_reference`（类别名 + sha256 摘要） | 新原因只用固定内部字符串构造，落库只有 `error_code="AdapterError"` + 64 位摘要 |

---

## 3. 各风险复现结果（修复前）与影响边界

复现方法：同一份新增测试文件，先把 `drift.py` 还原为 `git show HEAD:` 版本执行，再执行修复版。

| # | 假设 | 修复前实测结果 | 影响边界 |
| --- | --- | --- | --- |
| 1 | receipt 非对象导致 `AttributeError` | `AttributeError: 'list'/'str'/'int'/'bool' object has no attribute 'get'`，6 项定位 `drift.py:61`（回执取值） | 整批巡检抛异常 → 端点 500，**同批其他正常部署完全未被检查** |
| 2 | 异常 revision 被 `str()` 归一后误用 | `revision=7` 与后端 `"7"` 被判一致（无结论）；`{}`/`""`/`None` 回执与后端不同 revision 时**伪造 `revision_mismatch`**（断言 `[]` / `['revision_mismatch']`） | 异常值被"修正"成可比较字符串 → 漏报或误报 |
| 3 | 错误目标读回被当作可信读回 | 读回 target 为 `sandbox-other-tenant`、revision 相同时产出 `[]`（即当作"无漂移"） | 用**别的目标**的有效规则证明本部署一致 → 假阴性 |
| 4 | 跨租户 ChangeRequest / DesiredPolicy 被读取比较 | 合成其他租户策略被读取并参与比对，产出 `['missing_rules','undeclared_rules']`；**真实端点响应体与 Finding 中出现其他租户规则 endpoint 标记** | 跨租户规则回显（需"持久化层存在跨租户/悬挂引用"，见 §7 可达性说明） |
| 5 | 异常网络容器/行崩溃或误报 | 期望侧 `drift.py:80`：3 `AttributeError` + 2 `TypeError: unhashable type: 'list'`；读回侧 `drift.py:82`：3 `AttributeError` + 1 `TypeError: 'NoneType' object is not iterable`；`{}`/`""` 容器被 `or []` 悄悄当成空列表并产出 `['missing_rules','undeclared_rules']` | 崩溃（同 1 的整批影响）或把异常容器当合法空集 → 误报 |
| 6 | 混合批次无法完成正常记录检查 | 坏记录 `AttributeError` 直接中断循环，正常漂移记录无任何结果 | 可用性缺陷：单条脏数据使整个租户本轮巡检失效 |

同时确认**未被证伪**（既有行为已正确、本轮未重复实现）：合法 `error_reference` 脱敏、`AdapterError` → `unreadable`、`revision_mismatch`/`missing_rules`/`undeclared_rules` 正常语义、`check_policy_drift` 不自行提交。

修复后同一测试文件：**58 passed / 0 failed**；修复前同一文件基线 **47 failed / 11 passed**，其中 15 项为崩溃（上表 1、5 的堆栈定位），32 项为断言失败（把异常证据当可信事实、把不可核对当无漂移、跨租户回显）。

### 影响边界的重要限定（不做过度声明）

- 上述 1、2、5、6 可在**纯产品调用路径**上触发（持久化的异常 JSON 行 + 模拟适配器复现），不等同于真实 OpenShell 生产攻击。
- 第 3 项用模拟适配器复现：**当前 CLI 适配器回显请求 target**（`cli_backend.py:520`），真实 CLI 路径上不会自己产生目标错配；该项是**适配器纵深防御**要求，不据此宣称已在生产复现。
- 第 4 项**不能经合法 API 产生**：`prepare_deployment` 对 `ChangeRequest`/`Environment`/`RuntimeBinding` 与 `_policy_or_404` 全部强制 `tenant_id == identity.tenant_id`（`policies.py:441-458`），`execute_deployment` 的 `target` 也只来自同租户 `RuntimeBinding.backend_target_id`；因此跨租户引用只可能来自**历史/异常持久记录或带外写库**。本任务不修改数据库约束、不修复或迁移历史引用，只拒绝无法可信核对的证据。

---

## 4. 租户限定、异常隔离与同批继续处理

1. **租户限定**：`ChangeRequest` 与 `DesiredPolicy` 一律用显式 `select(...).where(id == ..., tenant_id == tenant_id)`，不再使用 `session.get()`（不以外键 ID、Deployment 归属或 ORM 缓存替代检查）。查不到本租户对象 → `unreadable`（`openshell_drift_policy_evidence_unavailable`）：**不读取对方策略正文、不把"找不到期望策略"解释成"期望没有网络规则"、不报告无漂移、不回显对方名称/规则/标识**。
2. **读回层面的整体作废**：读回同时是 revision 与网络两个维度的依据，因此读回结构或目标不可信时只产出单个 `unreadable`，不再推导任何其他结论。
3. **维度级隔离**：回执证据只影响 revision 维度，期望策略/网络证据只影响网络维度；一方不可核对时另一维度仍按各自可信证据比对（不丢弃可独立验证的事实，见 `test_receipt_absent_keeps_other_dimensions_checked`、`test_mixed_batch_keeps_checking_healthy_deployments`）。
4. **同批继续处理**：所有异常都收敛为当前部署的 `DriftResult` 并 `continue`，不中断循环；仅 `except AdapterError` 被捕获，编程/数据库等非预期异常照常抛出（`test_unexpected_backend_error_is_not_swallowed`）。
5. **结果顺序**：同一部署的 `unreadable` 结果排在漂移结论之前，便于端点响应与既有 upsert（每部署一个 open Finding）语义下优先暴露"证据不可核对"。

---

## 5. 保留的正常检测与审计事务

- `revision_mismatch`（high）、`missing_rules`（high）、`undeclared_rules`（medium）三条既有语义与严重级别不变，`allow/deny` 过滤、集合比较与排序模型不变（未做网络策略语义引擎重写）。
- `unreadable` 沿用既有 `kind` + `{"kind":"unreadable", "error_code", "error_digest"}` 结构与 `error_reference` 脱敏；**未新增结果枚举、未新增 API 字段**，`upsert_drift_findings` 与 `routers/inventory.py` 的 check-drift 端点未改动。
- `check_policy_drift` 仍不自行 `commit`；Finding + 审计 + outbox 仍在调用方的同一事务内（`test_check_stage_does_not_change_state_or_publish` 断言部署状态、回执、`verification`、策略状态、ChangeRequest 状态均不被检查阶段改动；`test_audit_failure_rolls_back_whole_persist` 断言审计失败时该租户 Finding/AuditEvent/OutboxEvent 行数与部署专属 Finding 全部回滚）。
- 部署状态不翻转、不自动关闭旧风险、不自动重新部署/修复/撤权/发布。

---

## 6. 实际执行的验证命令与结果

```bash
cd /home/maoyd/siq/siq-agent-security/apps/control-api
uv run --no-sync pytest -o addopts='' -q \
  app/tests/test_drift_evidence_boundaries.py --tb=short
# 结果：58 passed（修复前基线：47 failed / 11 passed）

uv run --no-sync pytest -o addopts='' -q app/tests/test_rules.py -k "drift" --tb=short
# 结果：4 passed, 28 deselected（既有漂移用例；筛选范围=test_rules.py 内名称含 drift 的 4 项）

uv run --no-sync pytest -o addopts='' -q \
  app/tests/test_rules.py app/tests/test_batch_shared_policy.py \
  app/tests/test_deployment_verify.py app/tests/test_deployment_verify_boundaries.py --tb=short
# 结果：80 passed（漂移消费者 + 冻结的 receipt verifier 既有测试，后者未改动）

uv run --no-sync ruff check app/drift.py app/tests/test_drift_evidence_boundaries.py
# 结果：All checks passed!

git diff --check                     # 通过（无空白错误）
grep -rnE '[ \t]+$' <新增文件>       # 无尾随空白
```

**未运行（有意，按任务要求）**：后端全量 pytest、前端/浏览器、Go 模块全量、`worker.py` 的 `run_drift` 集成（无对应既有测试；`run_drift` 直接调用同一函数，未改其调用方式）、真实 OpenShell、真实数据库/网关、任何安装或联网同步。
**失败项**：无（本轮无遗留失败用例）。

---

## 7. 范围外问题与未验证的真实环境性质

- **`upsert_drift_findings` 未修改**（按任务要求）。已观察到的既有行为，仅记录不外扩：同一部署多条结果时按 `rule_id + resource_ref + open` 幂等 upsert 只保留一条 open Finding，后写入的结果覆盖前一条的 `severity`/`risk_acceptance`/文案；因此本条"每部署可能多结果"的顺序差异会体现在持久化上（本轮以"unreadable 在前、漂移在后"使其优先暴露漂移结论）。属既有风险生命周期设计，不在本轮改动。
- **既有未改变的容忍语义（已按合同核对后保留，并如实标注限制）**：`Deployment.receipt IS NULL` 的 effective 部署仍只跳过 revision 维度而不产出独立结果——既有返回合同（`revision_mismatch`/`missing_rules`/`undeclared_rules`/`unreadable`）没有"回执证据缺失"这一状态，本轮不新增枚举也不扩展公共接口；相关限制在此明确记录，供主开发者决定是否另开任务。当前 CLI 生效路径（`policies.py:608-650`）总是与 `status="effective"` 同事务写入回执，Edge `publish_policy` 路径恒置 `failed` 且不进入本扫描，故该分支为历史/异常记录。
- **未验证的真实环境性质**：本轮全部结论基于隔离 SQLite + 模拟适配器；未连接真实 OpenShell 网关，未验证真实网关的 `policy get --full` 目标归属、真实 revision 形态或错误目标读回是否会在生产出现。第 3 项（错误目标读回）在当前 CLI 适配器上不可自产，属纵深防御。
- **未证伪项无需实现**：见 §3 末段。

---

## 8. 交付状态

- 未提交、未推送、未创建分支/PR、未部署、未改任何治理或台账文件。
- 工作树中其他开发线（Kimi 执行前绑定复验、Qwen 关联查询前端、GLM 环境列表分页、主开发者 Edge 周期计划归档恢复）的文件未被触碰。
- **待主开发者复核**：`app/drift.py` 的维度级证据隔离规则（§4.3/§4.5 的结果顺序）、§7 中"无回执"限制是否需要独立任务处理。

---

# 主开发者复核问题修复（CL-05-DRIFT-EVIDENCE-REVIEW-FIX）

本节为复核反馈后的**增量**记录，日期 2026-09-26。§1–§8 为上一轮（`CL-05-DRIFT-EVIDENCE-CLOSEOUT`）原始记录，**未删除、未改写**，其结论仍然有效（仅测试项数由 58 增至 98）。
本轮只修复两处已复现问题：①回执目标冲突未检查；②未知 `effect` 被当作允许规则。未做其他扩展或重构。

## 9.1 本轮修改文件

| 文件 | 动作 | 说明 |
| --- | --- | --- |
| `apps/control-api/app/drift.py` | 修改（本轮增量 +41 / −11；累计 +216 / −33） | 只改模块/函数文档、固定原因码常量、`_receipt_revision`、`_endpoint_set`，以及 `check_policy_drift` 内的回执调用点与比对分支 |
| `apps/control-api/app/tests/test_drift_evidence_boundaries.py` | 修改（新增 40 项；既有 58 项全部保留，共 98 项） | 先加负例跑出失败，再改产品代码 |
| `docs/development/enterprise-drift-evidence-closeout-handoff.md` | 追加本节 | 未删除任何旧记录 |

未改：`upsert_drift_findings`、`routers/inventory.py`（check-drift 端点）、`DriftResult` 结构、结果 `kind` 枚举、API 响应字段、`deployment_verify.py`、`routers/policies.py`、`binding_identity.py`、`models.py`、`schemas.py`、迁移、共享审计/权限/错误处理/适配器、前端/Edge/Connector/安装器、依赖与锁文件、公共台账与总任务书。

## 9.2 问题 1：回执目标冲突未检查（复现 → 修复）

**复现（修复前，真实 `check_policy_drift` + 隔离 SQLite + 模拟适配器）**：合成样例
`deployment.target="target-A"`、`receipt={"backend_revision":"1","target":"target-B"}`、读回 `target="target-A"`/`revision="1"`/`network=[]`、同租户期望网络为空：

| 断言 | 修复前实测 | 修复后 |
| --- | --- | --- |
| 结果不得为空 | `[]`（断言 `assert []`，即"检查完整且无漂移"的假象） | `['unreadable']` |
| 后端 revision 不同（`"2"` vs 回执 `"1"`）时不得据此报带外变更 | `['revision_mismatch']`（用**别的目标**的回执当作本部署证据） | `['unreadable']`，无 `revision_mismatch` |
| 网络维度独立可比对 | `['missing_rules']`（回执证据作废连累了 revision 维度却仍无**报告**） | `['unreadable','missing_rules']`（既如实报告不可核对，也不丢弃可独立验证的缺失事实） |
| 近似目标（首尾空白/大小写/换行变体）不得被归一 | 5/5 用例误判为无可信问题（`[]`） | 5/5 `['unreadable']` |

**修复**：`_receipt_revision(receipt, expected_target)` 在原有结构校验后，对**显式出现**的 `receipt["target"]` 做 `_usable_identifier` 与 `target != deployment.target` 的**原值**比较（不 trim、不 lowercase、不重定向）；冲突返回内部哨兵 `_TARGET_CONFLICT` → 调用方产出**既有** `unreadable` 结果，固定原因码
`openshell_drift_receipt_target_mismatch`（仍由 `error_reference` 生成脱敏摘要，仍是既有 `kind="unreadable"`，**未新增 kind / 响应字段 / 结果枚举**）。缺 `target` 键的旧回执保持兼容（`test_receipt_explicit_matching_target_keeps_legacy_comparison` 的第二个租户用例仍为 `[]`）。

**与既有先例一致**：冻结的 `deployment_verify.py:77-88` `_receipt_target_conflict` 对同一规则已给出相同语义——"旧回执合法地不带 target，保持兼容"、显式异常值不当作已核实冲突、原值比较。本轮使漂移模块与该已验收先例对齐，不引入第三种口径。

**可达性分类（不过度声明）**：当前产品生产者**均不会**写出与本部署目标不同的回执 target——CLI 应用路径 `cli_backend.py:642-653` 的 `_deployment_receipt(target=target)` 写入的是同一次请求的目标；`fake_backend.create_generation`（`fake_backend.py:225-240`）根本不写 `target` 键；Edge `publish_policy` 回执（`environments.py:579-582`）写 `{"status","error_code",**verification}` 且该路径恒置非 effective、不进入本扫描。因此本项属**适配器纵深防御 + 历史/带外回执记录处理**，**未在生产复现**，也不据此宣称已发生错配。

## 9.3 问题 2：未知 `effect` 被当作允许规则（复现 → 修复）

**复现（修复前）**：`_endpoint_set` 只校验 `effect` 是字符串，随后用 `effect != "deny"` 判定，于是未知取值被当成 allow 参与集合比对：

| 侧 | 合成样例 | 修复前实测 | 修复后 |
| --- | --- | --- | --- |
| 期望侧 | `[{endpoint: A, effect:"unexpected"}]`（后端 `[]`） | `['missing_rules']`（凭空产生"期望规则缺失"） | `['unreadable']` |
| 期望侧 | `[{endpoint: A, effect:"unexpected"}]`（后端 `[{A, allow}]`） | `[]`（混入集合后与后端相等） | `['unreadable']`，无 `undeclared_rules` |
| 读回侧 | 后端 `[{endpoint: A, effect:"unexpected"}]`（期望 `[{A, allow}]`） | `[]`（伪造"无漂移"） | `['unreadable']`，无 `missing_rules` |

失败参数：`unknown-string`、`empty-string`、`uppercase-allow`、`titlecase-allow`、`uppercase-deny`、`allow-trailing-space`（每侧 6 项）；非字符串取值（数字/布尔/`null`/数组/对象）上一轮已拒绝，本轮保留为回归护栏。

**合同依据（合法取值与缺省兼容）**：

| 事实 | 来源 | 采用语义 |
| --- | --- | --- |
| 编译侧只接受 `effect=allow`；`deny`、method、path、protocol 及一切未知字段在 `policy set` 前失败 | `packages/contracts/openshell-policy-safety.v2.md:35-37`；`policy_safety.validate_network_rules`（:184-185） | 显式 `allow` = 合法允许规则；显式 `deny` 按**既有比较模型**排除（本轮不改该模型，`test_deny_rules_still_excluded_from_comparison` 保留） |
| 读回生产者恒产出 `effect: "allow"` | `policy_safety.gateway_network_to_rules`（:206 起）、`cli_backend` 读回投影 | 读回侧合法显式值 = `allow` |
| 缺 `effect` 键的历史/既有记录存在且未被静态校验拦截 | `schemas.py:476` `network: list \| None`；`routers/policies.py:61-71` `_validate_policy_static` 只查 selector/enforcement_mode/secrets，**不含网络规则**；既有样本 `test_change_review.py:133` 即无 `effect` 键 | 保留既有默认 `_DEFAULT_RULE_EFFECT = "allow"`（"非 deny 即 allow"），**不新增限制、不误拒合法历史记录** |

**修复**：`_endpoint_set` 引入合同白名单 `_RULE_EFFECTS = ("allow", "deny")` 与默认值 `_DEFAULT_RULE_EFFECT = "allow"`；`effect = row.get("effect", _DEFAULT_RULE_EFFECT)` 后 `if effect not in _RULE_EFFECTS: return None`。非法取值 → 该维度返回"不可用"（`_NETWORK_EVIDENCE_UNUSABLE`，既有 `unreadable` 语义），**既不当作允许规则、也不静默跳过**（跳过会伪造 `missing_rules`/`undeclared_rules`）；未扩展通配、优先级、L7 限制或网络策略语义。

**可达性分类**：`POST /api/v1/policies` 的 `network` 无静态校验，故非法 `effect` 的**策略行可经合法 API 持久化**（该策略无法通过编译下发，`validate_network_rules` 会在 `policy set` 前拒绝）——本项按"合法 API 可达的持久化记录"处理，不是纯模拟场景；读回侧非法 `effect` 属适配器/网关纵深防御。

## 9.4 脱敏与既有边界保持

- 错配 target 原文、非法 effect 原文均不进入结果、真实端点响应体、Finding、审计与 outbox（`test_conflicting_receipt_target_never_echoed`、`test_illegal_effect_value_never_echoed` 覆盖；仅固定原因码的摘要出现）。
- 租户限定（`select(...).where(tenant_id == ...)`）、维度级证据隔离、`AdapterError` 之外的异常不吞、检查阶段不改部署/策略状态、不自动提交、审计失败整体回滚等 §4/§5 边界全部未改，既有 58 项测试全部保留通过。
- 未新增正整数/纯数字限制；字符串 `"0"` 仍合法可用（`test_string_zero_revision_is_usable` 保留）。

## 9.5 本轮验证命令与实际结果

```bash
cd /home/maoyd/siq/siq-agent-security/apps/control-api
uv run --no-sync pytest -o addopts='' -q app/tests/test_drift_evidence_boundaries.py --tb=short
# 修复前（同一文件、仅加负例）：23 failed / 75 passed
# 修复后：98 passed

uv run --no-sync pytest -o addopts='' -q app/tests/test_rules.py -k "drift" --tb=short
# 结果：4 passed, 28 deselected

# 主开发者上次执行方式的同款命令（两个文件 + 筛选）：
uv run --no-sync pytest -o addopts='' -q app/tests/test_drift_evidence_boundaries.py \
  app/tests/test_rules.py -k "drift or evidence" --tb=short
# 本轮结果：104 passed, 26 deselected
# 上一轮该命令：64 passed, 26 deselected；deselected 数不变，新增 40 项同时命中该筛选

uv run --no-sync ruff check app/drift.py app/tests/test_drift_evidence_boundaries.py
# 结果：All checks passed!

git diff --check            # 通过（无空白错误）
grep -nP '[ \t]+$' <本轮改动/新增文件>   # 无尾随空白
```

**口径说明**：`104 passed / 26 deselected` 是上述 `-k 'drift or evidence'` 命令在该次收集中的实际结果，**不是"全部测试通过"**；本轮未运行后端全量 pytest，也未运行前端/浏览器/Go、真实 OpenShell/网关/数据库，未安装依赖、未联网同步。

## 9.6 遗留与范围外（未处理）

- `receipt IS NULL` 的 effective 部署仍只跳过 revision 维度而无独立结果（§7 已记录：既有返回合同无"回执证据缺失"状态，本轮不新增枚举）。
- `upsert_drift_findings` 每部署一个 open Finding 的后写覆盖行为（§7），本轮未改。
- 本轮新增了内部固定原因码 `openshell_drift_receipt_target_mismatch`，使该类 `unreadable` 的 `error_digest` 与上一轮不同（响应结构、字段、kind 均未变）。若主开发者要求保持单一原因码，可回退为复用 `openshell_drift_receipt_unusable`，不影响判定逻辑。
- 未验证真实网关的 `policy get --full` 目标归属、真实回执 `target` 来源，以及生产环境是否会实际出现错配回执或非法 `effect` 读回。

## 9.7 交付状态

- 未提交、未推送、未创建分支/PR、未部署、未改任何治理或台账文件；工作树中其他开发线（Kimi 执行前绑定复验、Qwen 关联查询前端、GLM 环境列表分页、主开发者 Edge 周期计划归档恢复）的文件未被触碰。
- **待主开发者复核**：错配回执的原因码命名（§9.6 第三条）、非法 `effect` 按"该维度不可用"而非"整条部署作废"的处理粒度。
- **仅完成本次漂移证据验收修复，未提交、未部署，待主开发者复核；不代表 CL-05 或整体项目完成。**

## 10. 主开发者复核结论（2026-09-26）

两项退回问题已修复：显式回执目标错配不再产生空结果或基于该回执的 revision_mismatch；非法显式 effect 不再被当作 allow。缺省 target、缺省 effect、合法 allow/deny 与字符串 revision 原值比较保持兼容。各维度独立处理符合本次范围：不可信回执不消除可信网络差异，非法网络不消除可信 revision 差异。

接受固定内部原因码 `openshell_drift_receipt_target_mismatch`，不回退为结构异常的通用原因码。error_digest 是错误参考，不是权限或公共状态枚举；本轮核对的消费者没有按该固定摘要作业务分支，输出字段与 unreadable kind 均未改变。历史记录不回写。

主开发者实际执行：

```bash
cd /home/maoyd/siq/siq-agent-security/apps/control-api
uv run --no-sync pytest -o addopts='' -q app/tests/test_drift_evidence_boundaries.py app/tests/test_rules.py -k 'drift or evidence' --tb=short
uv run --no-sync ruff check app/drift.py app/tests/test_drift_evidence_boundaries.py
```

结果 **104 passed / 26 deselected**，仅既有 Starlette/httpx 弃用提示；Ruff、git diff --check 和新增测试/交付记录尾随空白检查通过。核对了错配目标及非法 effect 的持久化脱敏断言；其中目标用真实 mock 端点，effect 用真实产品检查/持久化函数，不将两者都描述成端点测试。本轮不重复跑全量，不为增加数量新增测试。

本次验收未发现需要继续改动的业务代码，仅追加本复核记录。CL-05-DRIFT-EVIDENCE-REVIEW-FIX 按本次范围验收通过；receipt=NULL 的检查完整性表达及单 Finding 聚合限制仍保留，不表示完整漂移治理已经完成。未触碰其他开发线、未提交、未部署、未连接真实后端。
