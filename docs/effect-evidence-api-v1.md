# EffectEvidence API V1（实验性）

API 位于现有 loopback daemon，沿用 Host/Origin 检查。效果观察者是管理端配置的独立身份；工具成功上报 `/v1/observe` 不会自动变成独立效果证据。

## 管理 observer

使用已配对的 admin session 调用 `POST /v1/effect-observers`：

```json
{
  "source": {
    "type": "host_observer",
    "source_id": "local-file-observer",
    "independence": "host_independent"
  },
  "scope": {
    "platform": "hermes",
    "session_id": "session-1",
    "agent_id": "agent-1",
    "task_id": "task-1"
  },
  "expires_in": 300
}
```

201 响应包含 observer_id、token、expires_in 和 scope=effect_observe，并设置 Cache-Control: no-store。仅将 token 交给指定 observer，不交给模型或工具适配器。内存仅保存 token 摘要；过期上限3600秒、活动上限128个，daemon 重启后须重新配置。

允许的来源组合：host_observer/openshell 对应 host_independent；provider_audit/test_oracle 对应 external_independent。此配置是管理端授权声明，不证明某个 provider 或 observer 实现已安装。

`DELETE /v1/effect-observers/{observer_id}` 使用 admin session，成功204、不存在404。撤销完成后不再接受该 token 的提交。

## 提交与读取

Observer 使用自己的 bearer token 调用 `POST /v1/effect-evidence`，正文遵循 [提交合同](../packages/contracts/effect-evidence-submit.v1.schema.json)。字段与 EffectEvidence 一致，但 signature 必须为空，由 daemon 完成关联、分类和签名。

- Source 三个字段必须与 observer 配置完全一致。
- action_id/decision_receipt_id 必须对应真实动作，且 platform/session/agent/task 与 token scope 完全匹配。
- 新提交沿用24小时动作关联窗口；observed_at 不得早于决策或晚于当前时间。
- resource_ref 使用动作 ResourceRefs 的 `<domain>:sha256:<digest>`，不提交明文路径、URL 或收件人。
- evidence_digest 为观测材料摘要；只提交摘要不会自动获得客观真实性证明。
- 独立 completed 证据关联被拒绝动作时，保存为 unexpected，并关联 unauthorized_effect_observed 事件；资源或效果不匹配归为 effect_scope_mismatch。

返回201的签名封套包含 evidence、finding_code、request_digest 和 task_id。相同 ID/请求幂等返回原封套；同 ID 内容变化409；无效关联400；observer 不匹配403；容量耗尽503。状态异常返回通用错误，不泄露文件路径。

Admin 可使用：

- `GET /v1/effect-evidence/{id}`：读取单份封套，不存在404。
- `GET /v1/actions/{action_id}/effect-evidence`：返回 `items`，按证据 ID 排序；无记录返回空数组，不能因此推断没有实际效果。

动作查询对有界目录中的记录逐份验签；损坏记录使查询失败，不能被静默忽略。当前上限8192份，分页和查询性能基线尚待完善。

## 当前验收边界

已验证管理/决策/observer 分权、来源冒充、任务错配、撤销、到期、服务重启 token 失效且证据保留，以及拒绝后效果的事件分类。测试 observer 为受控提交者；文件采样接口现已接入，详见下节；受控网络 oracle 已提供测试库；Completion API 见下节，尚未接入网络完成要求。同 UID host observer 不构成 OS 隔离。

## 服务端文件采样

已接入两阶段文件观察接口，使用上述 host_observer token：

1. 在目标工具执行前 POST `/v1/file-observations`，正文含 observation_id、action_id、decision_receipt_id、path、expected_digest、max_bytes。path 必须精确匹配动作资源，expected_digest 来自受信任务期望；max_bytes 为1–16777216。服务实际读取并返回 before 元数据，首次201、相同重试200。
2. 工具执行后 POST `/v1/file-observations/{observation_id}/finish`，正文仅含 path。服务再次读取，生成材料与签名封套，首次201、完成重试200。

两个接口均拒绝自报 before/after/source 字段。观测只读取文件，不会执行工具或授予写权限；被拒绝动作若出现实际文件效果，记录安全事件。原始路径仅用于瞬时读取，不存入 pending 或证据。

无文件为 failed/unexpected；检测到变化且匹配预期摘要为 completed/expected；相同内容和元数据不证明执行，返回 unknown。始终只标记 partial/host_independent。签名封套内 file_observation 保留前后大小、摘要、mtime 和采样时间。

当前 pending 最多128条，绑定原 observer token；撤销、到期、重启后不能继续该次采样。已完成证据仍可由管理端读取；跨重启恢复 pending 尚未实现。测试中 warn 正例遵循既有 advisory policy，并不证明 block 模式 Grant 准入链路；block 用例验证拒绝后效果事件。

## 查询任务效果完成状态

Admin GET `/v1/tasks/{task_id}/completion` 返回 [completion-status/v1](../packages/contracts/completion-status.v1.schema.json)，不提供写入完成状态的接口。签名 Intent V3 可通过 effect_requirements 声明 file.write 的资源摘要、预期内容摘要、最低独立性及覆盖范围。

- verified：每项要求都有匹配的独立签名材料，且没有遮蔽的未知、失败或冲突记录。
- incomplete：缺少证据或已知执行失败。
- conflicting：内容/效果冲突，或该任务存在已知安全事件。
- unknown：无要求（not_required），或材料/独立性/覆盖不足。

无任务404；同 task_id 对应多个 Intent 返回409，避免选择较宽的要求；损坏签名、材料或动作关联失败返回500，不能当作 verified。响应设置 no-store，每次重新读取已发布状态。

此状态反映已发生效果是否满足签名要求，不授予后续执行权限。它不是冻结任务的最终封账，也不是跨存储事务快照；新的证据可能改变下一次结果。Completion 现从完整验签回执链按引用恢复历史动作，支持超24小时已存证据；新采样/提交仍遵守原动作窗口。网络要求现支持 network.request：签名 expected_endpoint 固定 scheme/host/port，expected_digest 固定接收请求组合摘要；只接受 external_independent。Completion 同时核验 requested/received 两端与签名要求，不能仅凭主机摘要完成。当前限于受控 loopback oracle 材料，partial 不能满足 full。

## 受控网络服务器材料提交

管理员为受信测试服务器注册 `test_oracle/external_independent` 来源和精确任务 scope；该服务器使用独立 observer token POST `/v1/network-observations`，正文为 `observation_id`、`action_id`、`decision_receipt_id`、`observation`，结构见 [提交合同](../packages/contracts/network-observation-submit.v1.schema.json)。`NetworkOracle.Source()` 提供注册身份，`Material()` 只能从该实例实际接收事件派生材料。

服务根据凭据恢复来源，校验真实动作及 scope，再签名归档。首次及相同内容重试返回201和同一记录；同 ID 不同材料409，凭据或scope错误403，伪造接收事件身份等非法材料400。decision/admin token 不能直接提交，正文不能自报 source、scope 或 authorized。管理端可通过既有证据 GET 查询，已保存记录跨重启可读；observer token 重启失效。

这是受信 loopback 测试 oracle 的集成接口，独立性依赖管理员对服务器身份与凭据隔离的配置；不将任意客户端上传的日志视为独立真相，也不代表已接入生产网络审计。拒绝动作后实际接收到请求会生成 `unauthorized_effect_observed`，不会被解释为正常完成。
