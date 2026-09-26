# 企业批次显式执行 v1

POST `/api/v1/deployment-batch-drafts/{draft_id}/execute`，返回 HTTP 200 和
`Cache-Control: no-store`。这是新的显式执行协议，不复用草稿 revalidate 请求为执行授权。

请求仅含：

```json
{"schema_version":"enterprise-batch-execute/v1","preview_digest":"64位小写十六进制摘要","confirm_execution":true}
```

confirm_execution 必须为 JSON 布尔 true，不接受 1、字符串或缺省；该确认仅确认
执行已获独立审批的变更，不是审批接口。租户/操作者来自验证身份，禁止额外身份、
目标或策略字段。先按草稿租户定位 404，再核对原操作者、policy:read、env:read、
policy:manage；整批和逐项沿用既有审批、运行绑定、目标权限、摘要及期限复验。

唯一执行身份是草稿至批次的数据库唯一预留；不接受另一个执行幂等键。
首次整批预留和审计提交后逐项执行，失败/未知/到期停止后项。已有预留的重复请求
只读结果，不恢复 pending、不重放已成功项，也不续期。过期且无预留拒绝 409；
过期且有预留可读取结果。不能承诺跨后端外部原子性或自动回滚先前成功项。

响应 schema_version=`enterprise-batch-execution/v1`：reservation_id、draft_id、
state（unconfirmed/needs_attention/recorded）、items（既有 SubmissionOut 数组）、
retry_executes=false。HTTP 200 表示成功取得逐项结果，不表示整批生效；recorded
包含 sent，只有独立后端读回才能说明 effective。未知结果使用已有只读 reservation
接口查询调查，不允许通过删除占位重新执行。

v1 草稿/预览/占位读取响应中的 capability=false 保持兼容，表示这些旧协议本身不
发起执行；新客户端必须显式集成本执行协议，不能把旧标志改为审批通过或恢复令牌。
用户可视化确认、共享影响预览、权限收窄/撤销转换仍需前端和领域层实施，本接口
不自动创建策略或批准变更。没有本协议集成的前端仍不能进行批量执行。

预留审计失败不执行并回滚；执行结果不明保留未知。服务异常不返回内部堆栈或原始
后端错误；调用者应使用只读接口核对是否已有预留，而不是推断失败即无副作用。
