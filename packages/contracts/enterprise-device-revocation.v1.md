# Enterprise device revocation v1

ENT-021：管理端吊销已注册 Edge 控制面凭据，不是撤销智能体业务权限。

## 接口及授权

- `GET /api/v1/environments/{environment_id}/devices/{device_id}/credential-status`：`env:read`。
- `POST /api/v1/environments/{environment_id}/devices/{device_id}/revoke`：`edge:manage`。
- 两者先通过 Environment.tenant_id 与 EdgeAgent.environment_id 联结定位对象，跨租户、错误环境及不存在统一 404，再检查权限返回 403。不接受客户端 tenant。
- POST 严格 body：`schema_version: "enterprise-device-revoke/v1"`、`confirm_device_id`（1–64 字符，必须与路径一致）。禁止额外字段。不接收自由文本理由，避免凭据或敏感原文进入审计。

## 返回与恢复

两接口返回同一白名单投影：schema_version=`enterprise-device-credential-status/v1`、environment_id、device_id、status=`active|revoked`、revoked_at（未吊销为 null）、runtime_permissions_changed=false。响应 Cache-Control: no-store。

active 仅表示该记录尚未吊销，不表示设备在线、凭据已持有或保护有效。
POST 成功返回 revoked。重复 POST 返回原吊销时间，不重复审计或修改状态；响应丢失可先 GET 核对。不提供重新启用接口。

## 事务与安全边界

首次吊销条件更新 revoked_at（仅 null→服务端时间），与 `edge.device.revoke` 审计及 `edge.device.revoked.v1` outbox 同事务；提交前失败整体回滚，返回通用 503，不能以部分成功响应。提交结果不确定或提交后响应失败，应先 GET 核对，不能把 503 解释成必定未吊销。审计只含环境/设备标识；原操作者来自验证身份。

首次转换的审计与 outbox 使用请求中间件已规范化的 request_id，与响应头一致；不直接复制原始请求头。可按审计查询合同以 request_id、resource_type=edge_agent、resource_id=device_id 和 action=edge.device.revoke 组合查回。请求编号仅用于关联，不是身份、审计主键、幂等键或执行效果证明。幂等重试可能具有新的响应请求编号，但不会改写首次事件的编号或追加虚假状态转换；此时应按设备对象查原始事件，而不能以重试编号查不到事件推断未吊销。

提交后，后续经现有在线认证入口的心跳、领取任务、上传、回执及注册恢复拒绝旧设备身份。已经通过认证并在途的请求不承诺中断；离线进程不会被远程终止。该接口不删除设备、候选、证据、任务、审计或策略，不放宽或撤销现有运行保护，不标记权限已撤除。没有新数据库字段或迁移。

并发首次吊销由数据库条件更新保证最多一次状态变更及配套事件；SQLite 隔离测试不冒充生产 PostgreSQL 并发验证。前端确认、凭据轮换、运行绑定失效联动、原生设备生命周期和生产验收仍需独立交付。
