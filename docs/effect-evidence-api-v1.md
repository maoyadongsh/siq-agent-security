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

已验证管理/决策/observer 分权、来源冒充、任务错配、撤销、到期、服务重启 token 失效且证据保留，以及拒绝后效果的事件分类。测试 observer 为受控提交者；文件前后状态观测、网络服务端 oracle 与 Completion API 尚未接入。同 UID host observer 不构成 OS 隔离。
