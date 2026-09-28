# WorkBuddy 本地失败证据 v2

`pending_decision/v2` 是未签名、本机 hook 产生的失败事件，不是服务端策略裁决。旧 `pending_decision/v1` 继续读取；普通旧适配器继续写 v1。新记录最多 8192 字节，不含工具参数、凭据、ACL 主体或网络异常原文。

新增 origin=`local_hook`、stage、reason_code，以及可选 native_session_id/native_call_id、派生 session_id/tool_call_id 和 action_digest。只有完整严格解析通过的输入才能携带调用字段；解析失败不补造 ID。摘要为 `SHA256("workbuddy-local-action/v1" + NUL + canon({session_id, tool_call_id, tool, params}))`。此摘要和 native ID 都不是 Authority。

Pre 失败 outcome=`deny`；Post 缺少已确认观察 outcome=`unconfirmed`，不声称阻止已经发生的操作。stage 区分 parse/bootstrap/enrollment/correlation/decision/observation。reason_code 为有界固定类别，普通模型输出不包含内部私密对象诊断。

提升产生 `runtime-receipt/v2` / record_type=`local_failure`，沿既有真实签名与哈希链追加；issued_at 是提升时间，local_origin.recorded_at 保留原始事件时间，local_origin.signed 仍为 false。来源为本地未签名材料，签名只证明提升记录，不认证其为在线裁决。outcome=unconfirmed 对应 action=unknown；不赋予有效 Authority、policy_action 或 matched Grant。旧 v1 原记录和既有回执字节不改写。

前端和导出必须区分 local_failure 与决策/成功 observation；它不能证明某工具当前受保护、不能恢复授权或触发 uncertain 重放。版本化 schema 是字段事实源，旧 schema 不原地扩写。
