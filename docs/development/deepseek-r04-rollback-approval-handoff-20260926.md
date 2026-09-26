# R04 独立回滚审批：只读合同草案交接（2026-09-26）

本文件是 R04 缺口「**独立回滚审批**」的交接材料。**本轮只交付只读合同草案与就绪度核对，未实现审批写入路径、未接线、未改回滚语义。** 范围与主开发者 2026-09-26 的答复一致：「先只出只读合同草案（推荐）」——不解除 ENT 缺口，但把决策所需信息补齐。

## 1. 交付了什么（4 个新文件）

| 文件 | 作用 |
| --- | --- |
| [enterprise-rollback-approval.v1.md](../../packages/contracts/enterprise-rollback-approval.v1.md) | 合同草案：7 条要素、四值状态词表、三条不变量、结论词表与可达性、与既有实现的关系 |
| [rollback_approval_readiness.py](../../apps/control-api/app/rollback_approval_readiness.py) | 内部只读就绪度核对（纯函数 `evaluate(facts)` + 今日快照 `requirements_table()`） |
| [test_rollback_approval_readiness.py](../../apps/control-api/app/tests/test_rollback_approval_readiness.py) | **11 条**用例：三条不变量逐条钉住 + 纯函数/确定性 + 源码只读边界 |
| 本文件 | 交接：决策要答什么、若批准实现的最小方案、证据与命令 |

**命令与结果**（可复验）：

```bash
cd apps/control-api
.venv/bin/python -m pytest app/tests/test_rollback_approval_readiness.py -p no:randomly   # 11 passed
.venv/bin/ruff check --no-cache --config pyproject.toml \
  app/rollback_approval_readiness.py app/tests/test_rollback_approval_readiness.py          # All checks passed!
```

## 2. 今天读到的事实（只读快照，非"应该是什么"）

7 条要求里：**0 条成立**、**5 条 `absent`**、**1 条 `declared_only`**、**1 条 `not_determinable`** → 结论 `rollback_approval_not_ready`。

| 有东西的两条 | 实际是什么 |
| --- | --- |
| 要求 6「审批证据不可由请求正文覆盖」→ `declared_only` | 只有**声明**：`app/adapters/openshell/contracts.py:239-240` 的 `RollbackAuthorization` 注明"仅由私有操作记录和实时读回构造"。**声明不是证据**。 |
| 要求 3「审批者 ≠ 申请者 ≠ 操作者」→ `not_determinable` | 本层看不到人的身份（只有令牌/角色），**无法判定**——且**自述不得越过不可观测性**。 |

其余 5 条（独立审批者身份、不把复验冒充审批、审批与这一次操作绑定、审批有效期、撤销后必须被拒）**今天都没有证据源**。

**最容易被误认的一条**：回滚链**已有**执行前复验（`app/routers/policies.py:939` `authorize_rollback`，写前重查绑定/目标/端点指纹/网关名摘要，配套 `:859` `_rollback_live_chain`）。它证明"意图未漂移"，**不**证明"有第二个身份为这次操作担责"。两者都必要，**不可互相替代**——本层只把这个缺口记下来，不假装它已被覆盖。

## 3. 本层明确不做的事

- **不是**审批实现、**不是** HTTP 接口、**不是**回滚执行器：`runtime_effect` 恒为 `"none"`，不读库不写库、不产生审计/outbox/任务、不发起外部探测。
- **不产生** `effective`，**不产生** `enforcement_verified`（保留值的唯一合法生产者见执行记录 R09.2）。
- **未**改 `execution_confirmation_supported`（任务书 R04 硬约束：不得擅自改为 true）。
- **未**选定审批人、**未**定义审批凭证字段、**未**设定有效期——这些是业务决策，本节不替答。

## 4. 需要主开发者决策的问题（逐条给选项与影响）

**Q1｜回滚是否必须与部署职责分离？**
- **A（要分离）**：审批者不得是发起部署/执行回滚的同一身份。影响：需要第二条可识别身份 → 与现有 `policy:manage` 单方即可回滚的语义**不兼容**，属行为变更，需独立授权与迁移考虑。
- **B（不分离，仅要求"二次确认"）**：影响：只是把一次点击变成两次，**不增加可追责的第二身份**，不满足要求 1，不能算独立审批——若选 B，本层应保持 `not_ready`，且**不得**声称已具备独立审批。
- **C（暂不定）**：维持现状 `rollback_approval_not_ready`，回滚保持 `policy:manage` 单方。影响：缺口保持可见，本轮交付即为终态。

**Q2｜若选 A：审批凭证由谁签发、含哪些字段、有效期多久？** 最小可用集合（对应要求 1/4/5）：`approver_identity`、`operation_id`、`target`、`current`/`restore` 摘要、`issued_at`/`expires_at`、撤销位。**影响**：字段一旦定死会进合同与审计，后续扩展需新版本（仓储既有"版本导航"约定）。

**Q3｜审批记录存在哪、是否与回滚同事务？** 影响：要求 7（撤销必须生效）与"审批审计同事务"（原因码 `approval_audit_not_in_same_transaction` 已预留）都取决于此；选"另库/外部系统"会引入失败关闭与跨库一致性要求。

**Q4｜`RollbackAuthorization` 的"仅由私有操作记录构造"要不要从声明升级为证据？** 升级需要一次**真实**的"请求正文携带审批字段被拒"的观测（不是读代码）。影响：这是要求 6 从 `declared_only` 变 `present` 的唯一途径；**不得**用"代码里这么写的"当作证据。

## 5. 若批准实现，最小方案（**待批准，本轮未做**）

1. **只加一处写前检查**，与既有复验同一位置（`authorize_rollback` 内），不新建旁路：先跑既有复验，再跑"审批存在且有效且绑定本次操作"。
2. **审批来源必须是私有记录**：沿用 `RollbackAuthorization` 的构造约定（不接受请求正文覆盖），**不新开请求字段**。
3. **失败关闭**：缺审批 / 审批过期 / 审批与操作不匹配 / 审批已撤销 → **409 + 零状态写入 + 审计**（沿用 `deployment.rollback_refused` 风格，新增固定拒绝码）。
4. **两条分支一致**：R05.5 已把授权链判定抽为唯一函数，审批判定必须同样只写一处，避免再次出现"一条分支有、另一条没有"。
5. **合同兼容**：不改既有响应字段，只新增拒绝码；`enterprise-rollback-approval.v1.md` 升版而非原地改语义。
6. **测试**：每条要求至少一个正例 + 一个反例（"审批缺失却放行""过期仍放行""换一个 operation_id 仍放行"必须被拒）；反证要能证明非空跑。

**前置依赖**：上面 4 个问题未答之前，任何实现都会替业务做决定。因此本轮**不实现**。

## 6. 本层自身的诚实边界

- **一处自查出的缺陷已修**：首版用集合成员判定取值，导致 JSON 里的数字 `1` 因 `1 == True` 被当成"成立"。已改为**按类型严格**判定（只有布尔 `True` 或 `"present"`/`"verified"` 才可能成立），并由 `test_unrecognized_value_is_never_treated_as_present` 钉住。**不是**测试放宽，是模块修正。
- **一个结论档经本层不可达**：`rollback_approval_requirements_met_but_not_wired` 因不变量 2 恒不可达（第 3 条永不可能 `present`）。这是**设计事实**，测试 `test_met_but_not_wired_is_unreachable_through_this_layer` 明写钉住，未伪装成可达。
- 本层**不构成**任何"回滚更安全了"的结论；它只把"缺什么"写成可核对的形式。
