# 独立回滚审批 v1

R04 增量（只读合同草案）。与 [enterprise-binding-invalidation-surface/v1](enterprise-binding-invalidation-surface.v1.md)、[enterprise-binding-evidence-readiness/v2](enterprise-binding-evidence-readiness.v2.md) 同族：**内部只读投影，不是 HTTP 接口，不是审批实现，不是回滚执行器，不是执行授权**。本版本不新增端点、不新增迁移、不改任何既有响应、**不接线**。

本文件是**草案**：它把"独立回滚审批"这件事拆成 7 条可逐条核对的要素，并如实登记**今天哪几条有证据、哪几条没有**。它**不**定义审批流程、**不**选定审批人、**不**解除任何 ENT 缺口。是否实现独立审批属于**业务决策**（回滚是否必须与部署职责分离、由谁批、凭证含哪些字段），本文件不替该决策给出答案。

## 解决的问题

仓储已有回滚链（`APP.POST /api/v1/deployments/{deployment_id}/rollback`），也已有**执行前复验**：openshell-cli 分支在写回滚前调 `app/routers/policies.py:939` 的 `authorize_rollback`，其 docstring 写明"写前重新查询当前授权链；**不使用申请中的 evidence 决定可否回滚**"，逐项复验绑定仍权威、目标权威未变、端点指纹与网关名摘要与回执一致（`_rollback_live_chain` 见 `:859`）。

但**复验不是审批**，两者证明的不是同一件事：

| | 证明什么 | 谁做的 | 能否互相替代 |
| --- | --- | --- | --- |
| 执行前复验 | "提交的意图**仍与当前状态一致**" | **同侧**、**同一请求路径**内的服务端重查 | **不能** |
| 独立审批 | "**另一个身份**为**这一次具体操作**承担了责任" | 本层**看不见** | **不能** |

历史风险：把"复验通过了"当作"有人批过了"，从而认为回滚已有第二双眼睛。本文件只把这个缺口如实记下来。

## 只读边界

`app/rollback_approval_readiness.py::evaluate(facts) -> dict` 是**纯函数**：不读库、不写库、不产生审计/outbox/任务、不发起外部探测、不扫描宿主，`runtime_effect` 恒为 `"none"`。它只把调用方给出的 `facts` 逐条判成四种状态之一，并给出"今天从哪能读到"的快照。

- 取值判定**按类型严格**：只有布尔 `True` 或 `"present"`/`"verified"` 才可能记成立；数字 `1`/`0.0`、任意未知字符串一律 `not_determinable`（不得因 Python 里 `1 == True` 而悄悄写成"成立"）。
- 入参中**缺失的键**等同于 `None`，记 `absent`，**不**记成立。
- 返回值是副本；改动返回值不影响模块常量，**不影响下一次判定**。

## 7 条要求（逐条附今日证据源）

来源：`app/rollback_approval_readiness.py::REQUIREMENTS`（`requirements_table()` 给出同一份快照）。

| # | 要求 | 今日证据源 | 今日状态 |
| --- | --- | --- | --- |
| 1 | 存在**独立**审批者身份（不是执行者、不是请求者） | **无**。回滚链上只有调用者身份与 `authorize_rollback` 的活体重查 | `absent` |
| 2 | 不把执行前复验**冒充**独立审批 | `app/routers/policies.py` 的 `authorize_rollback` 只做绑定/目标/指纹复验 | `absent` |
| 3 | 审批者 ≠ 申请者 ≠ 操作者（职责分离） | **无法判定**：本层看不到人的身份，只能看到令牌/角色 | `not_determinable` |
| 4 | 审批记录与**这一次**操作绑定（operation_id + target + current/restore 摘要） | **无**。`deployment.verification.rollback`（`policies.py:982`）只记回滚结果 `restored_revision`/`restored_digest`/`result`，不记审批来源 | `absent` |
| 5 | 审批有效期（相对执行时刻的窗口） | **无** | `absent` |
| 6 | 审批证据**不可**由请求正文覆盖 | **只有声明**：`app/adapters/openshell/contracts.py:239-240` 的 `RollbackAuthorization` 注明"仅由私有操作记录和实时读回构造，不接受请求正文覆盖" | `declared_only` |
| 7 | 审批被撤销后，回滚必须被拒 | **无** | `absent` |

今日结论：`rollback_approval_not_ready`（**0 条成立 / 5 条 `absent` / 1 条 `declared_only` / 1 条 `not_determinable`**，合计 7 条；计数按条不按权重）。

## 状态词表（固定四值，无"部分成立"）

| 值 | 含义 |
| --- | --- |
| `present` | 有**本层之外的**、可核对的证据源（本层不生产证据，只登记事实取值） |
| `absent` | 明确没有（今日 5 条属此类） |
| `declared_only` | 只有**声明**：合同写了、字段声明了、文档描述了 |
| `not_determinable` | 由记录**无法判定**（含"未识别取值"，见下） |

## 三条不变量（写死在判定里，测试逐条钉住）

1. **声明不是证据**：任何"合同里写了/字段已声明"的项一律记 `declared_only`，**不计入**成立。原因码固定为 `declaration_is_not_evidence`。
2. **不可观测就是不可观测**：本层看不到人的身份，故第 3 条**即使被自述为 `present` 也降级**为 `not_determinable`（原因码 `human_identity_cannot_be_observed_by_this_layer`）——**自述不得越过不可观测性**。
3. **本层不产生任何运行时效果**：`runtime_effect` 恒为 `"none"`，`independent_approval_supported` 恒为 `false`，`enforcement_verified_produced` 恒为 `false`；`effective` 与 `enforcement_verified` **都不由本层产生**。

## 结论词表与一处必须说清的可达性

| 结论 | 含义 | 当前可达性 |
| --- | --- | --- |
| `rollback_approval_not_ready` | 至少一条要求没有证据 | **可达**（今日结论） |
| `rollback_approval_requirements_met_but_not_wired` | 7 条**全部**有证据，但**仍然没有接线** | 经本层**不可达** |

不可达的原因是设计结果、不是缺陷：由不变量 2，第 3 条在本层永远只能是 `not_determinable`，所以 `全部 present` 恒为假。保留该档是为了把上限写死——**"全部成立"也只是"未接线"**，绝不会变成"已生效"。真正的"全部成立"必须由本层之外的、能给出独立审批者身份与一次性操作绑定的生产者举证；本模块不假装拥有它。

## 原因码（固定词表）

`no_independent_approver_identity`、`live_chain_recheck_is_owner_side`、`requester_equals_operator_unobservable`、`no_approval_record_bound_to_operation`、`no_approval_validity_window`、`no_revocation_path`、`approval_audit_not_in_same_transaction`、`request_body_override_only_declared`、`declaration_is_not_evidence`、`human_identity_cannot_be_observed_by_this_layer`、`fact_value_unrecognized`、`fact_missing`。**不得临时拼字符串**；成立项的原因码为空串。

## 与既有实现的关系（不重复实现）

| 既有件 | 本文件如何看待它 |
| --- | --- |
| `app/routers/policies.py:859 _rollback_live_chain` | 执行前复验的唯一判定处，属要求 2 的证据源；本层不复制其逻辑 |
| `app/routers/policies.py:939 authorize_rollback` | 同侧写前重查（`policy:manage` + 活体链 + 指纹/网关摘要比对），**不**构成独立审批 |
| `app/adapters/openshell/contracts.py:239-248` `RollbackAuthorization` / `RollbackAuthorizer` | 要求 6 目前**只有声明**；该类型"仅由私有操作记录和实时读回构造"是设计意图，本层不据此记成立 |
| `deployment.verification.rollback`（`policies.py:982`）、审计 `deployment.rollback` / `deployment.rollback_refused` | 记录的是**回滚结果与拒绝**，**不是审批**；不得当作审批记录 |

## 非声明

本文件**不是**审批实现、**不**新增端点、**不**改变回滚语义、**不**记录或产生任何 `effective` 事实。**不**解除 ENT 缺口；**不**声称回滚已具备职责分离。今日状态是 2026-09-26 的只读实测快照，随实现变化需重测——**它描述的是"今天读到什么"，不是"应该是什么"**。独立回滚审批是否上线属业务决策；在决策作出前，回滚保持现状（`policy:manage` 持有者可单方回滚，两条分支一致）。
