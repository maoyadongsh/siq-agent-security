# OPT-07：策略语义与部署入口验证

日期：2026-10-07。开发分支 `codex/security-optimization-20261007`，对照基线 `fa908fdf`。

## 变更与语义

本批按 [更新语义合同](../../packages/contracts/desired-policy-update-semantics.v1.md) 修正三类问题：Python 编译时拒绝被忽略的 filesystem 字段及非法列表；Go 编译保留空对象与空网络列表的明确意图；本地管理员网络替换接口拒绝缺少/null 的 network。

静态规划现在区分“字段不存在”和“明确 null 值”，空 process 补丁则保持当前状态。缩短或清空文件路径列表要求 generation；当前 OpenShell 动态入口不能执行时拒绝，不能仅更新网络并报告静态权限已改变。完整后端快照及未知静态扩展仍原样保留。

新增 15 条共享编译向量，历史 v1 向量及签名材料不改。Go `CompilePolicy` 的修复是编译组件对等性，不表述为所有本地执行链已经通过该函数执行；本地真实网络写入仍由独立 OpenShell writer 负责。

## 可达入口与授权边界

| 入口 | 合同与当前核查 |
| --- | --- |
| `POST /api/v1/deployments` | 保留支持的旧入口；无预览摘要，直接基于当前已审批变更执行共享 prepare/execute，不能指定任意 target。 |
| `POST /api/v1/deployment-preview` | 只读预检，不执行策略；生成包含主体、策略、binding、后端状态与授权来源的摘要。 |
| `POST /api/v1/deployment-preview/submit` | 相同预检后比较摘要；摘要漂移拒绝；共享 execute。 |
| `POST /api/v1/deployment-submissions` | 摘要确认、持久唯一 reservation、提交后再预检；重复提交只读既有状态。 |
| `POST /api/v1/deployment-batch-drafts/{id}/execute` | 明确确认、有效草稿和批次摘要；批量 reservation 后逐项复验，未知效果不重放。 |
| 本地 `/v1/openshell/apply` | 本地管理员凭据、loopback/Host/严格请求解析；仅网络替换与 revision/digest 检查。需要显式 network 数组，不接受静态段。不是企业租户或审批 API。 |
| 本地 session policy execute | 会话、有效 Grant、签名预留及目标上下文约束；网络从可信状态推导。沿用现有会话执行测试，不把直接管理员入口混称 Agent 自主授权。 |
| CLI `openshell apply` | 本机操作者边界，要求 target、expected revision、allow、binary；不支持任意静态生成或隐式清空。 |
| Edge task runner | 当前执行扫描/Skill 扫描；其他 task type 返回 unsupported，不能作为真实 OpenShell 写者或权限效果证据。 |

旧前端 `createDeployment` 定义当前无调用者，但本批保留兼容；不把删除客户端函数当作服务端安全修复。企业所有写入口均使用共享后端授权，不因旧接口不要求预览而跳过审批、租户、binding 或目标授权。

## 验证

- 共享编译：历史向量与新增 15 条语义向量在 Python/Go 两侧通过。
- 静态规划：10 条新增反例/兼容案例涵盖省略、null、空段、清空/缩短路径列表、空 process、相同 process 字段、缺失字段与明确 null；要求 generation 的请求未发生外部写入。
- 企业入口矩阵：**32 项通过**。四条写路径各覆盖一次成功及重复投递、无权限、跨租户、审批失效、binding 撤销、目标漂移、静态缩权与未知 filesystem 意图。成功只写一次；所有拒绝均无新增 deployment、EdgeTask 或 operation，无外部 policy set。
- Python 全量：**2,486 通过、1 条既有 wire sample 条件跳过**，182.49 秒。该轮收集发生在新增入口矩阵之前，32 项矩阵是独立通过记录，不相加冒充同次全量。
- PostgreSQL 隔离 harness：**31 项检查通过**，包括当前在线部署、持久恢复、并发/迁移守卫。
- 本地 HTTP：缺省/null/static 请求零后端调用；显式 `[]` 通过完整读回并成为 no-op。旧实现对缺省和 null 请求会调用后端并返回成功，负向覆盖确认。

最终 Go 全量 **44 个有测试包通过**（另 10 个无测试包），`go vet ./...` 通过；grant/server 的 race 通过，server race 用时 88.643 秒；linux/amd64、linux/arm64、darwin/arm64、windows/amd64 四目标构建通过。交叉构建不等于 Windows/macOS 原生验收。企业矩阵使用受控 CLI runner、独立测试身份及合成授权文件，不是新增真实业务效果报告；真实业务闭环继续由 OPT-08–10 验收。

## 可追溯记录

原始日志位于忽略目录 `var/optimization-20261007/`：`opt07-control-all.log`、`opt07-entry-matrix-final.log`、`opt07-postgres.log`、`opt07-local-apply.log`、`opt07-python-negative.log`、`opt07-go-negative.log`、`opt07-local-negative.log`、`opt07-go-final-all.log`、`opt07-go-final-vet.log`、`opt07-go-final-race.log`。旧代码通过隔离 Python 模块/Go overlay 加载，没有替换工作树实现。

首次入口矩阵发现测试预期状态码将目标授权拒绝误写成 502，实际合同为 409；随后跨用例固定目标名触发数据库唯一约束，已改为每例独立目标。两项均为夹具修正，原失败日志保留，不计入最终通过分母。
