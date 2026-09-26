# 企业批次执行占位 v1（内部创建，HTTP 只读查询）

reserve_batch 只接受已存在、归属匹配的草稿和其摘要。全部目标复验及整批摘要
匹配后，在同一数据库事务保存批次、各项 Deployment/DeploymentSubmission 以及
逐项 deployment.reserve 和批次 deployment.batch_reserve 审计。任一失败全部回滚。
有效期限在预检前、预检后及提交前检查。单项 request_digest 与现有单项接口共用。

草稿至批次唯一，变更至单项提交的既有唯一约束保留。已有批次只返回批次记录，
不返回新的可执行项；首次成功才返回本进程新建项供后续受控编排使用。该返回值
不是可持久化恢复令牌，进程丢失后不可从 pending 行重建执行调用。

占位层本身不调用后端 apply，也不更改审批。执行接口现由独立的
[显式执行 v1 协议](enterprise-batch-execution.v1.md) 提供，不复用只读协议为执行授权。
本 v1 草稿/占位投影的 capability=false 保持兼容，客户端必须显式集成新执行协议；
权限收窄转换和前端批量交互仍未完成。
迁移 0025 有记录时拒绝降级，不能通过删除未知占位恢复执行机会。

GET /api/v1/deployment-batch-drafts/{id}/reservation 提供逐项持久结果查询，复用
草稿租户定位、原操作者及 policy:read/env:read 检查。未建立占位返回 404
batch_reservation_not_found。响应包含 schema_version=enterprise-batch-reservation/v1、
id、draft_id、state、items（原 SubmissionOut）和 execution_supported=false。

校验占位 ID 列表数量/唯一性、每项提交及部署的租户、变更、环境、绑定、目标、
预览摘要和操作者请求摘要。任一不一致整批拒绝 409，不返回部分结果。no-store。
聚合优先级 unconfirmed > needs_attention > recorded。pending 仅表示执行结果
尚未确认，不证明进程仍运行，也不表示可安全重试。recorded 包括 sent，不等于
整批 effective；必须逐项查看 deployment_status。过期草稿仍可查询历史结果。
查询不访问 OpenShell、不变更占位，不触发执行、重试、续期或补写审计。

内部 execute_batch 只编排本次 reserve_batch 返回的新建项，逐项沿用单项执行阶段。
期限在每项开始前及该项重新预检后检查。遇到失败或未知结果停止后续项；仅当前
进程确定尚未进入执行阶段的后续项可记录 failed/backend_mutated=false，且状态与
审计同事务。当前项若结果不明，保持原持久状态，不能改成无副作用失败。
停止记录失败返回 batch_stop_unconfirmed，回滚未提交标记，仍可用只读接口调查。
进程丢失后重试只读已有占位，即使某些项从未开始也不自动重建执行。
此内部编排由上述显式执行接口调用；外部后端没有跨目标原子性，可能出现部分生效。
独立审批、目标 CAS、执行后读回沿用单项流程，recorded 不等于整批 effective。
