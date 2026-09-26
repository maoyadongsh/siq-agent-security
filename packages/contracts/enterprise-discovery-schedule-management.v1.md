# 企业周期发现计划管理查询 v1

本文记录已实现的只读分页查询行为，供企业端环境页面消费；不设计新 API，不改变既有创建/撤销 POST 与设备确认语义（见 [enterprise-discovery-schedule.v1.md](enterprise-discovery-schedule.v1.md)）。查询只呈现已保存记录，不证明设备在线、扫描执行或防护生效。

## 端点与权限

GET `/api/v1/environments/{environment_id}/discovery-schedules`：先按认证租户定位环境，不存在或跨租户统一 404；再要求 `env:read`（403）。租户仅取自验证身份，不接受查询或载荷覆盖。响应 `Cache-Control: no-store`。GET 无状态修改：不新增调度、任务、确认、审计或 outbox 事件，不调用预约或 tick。

## 顶层字段与分页

顶层精确字段为 `schema_version`、`environment_id`、`evaluated_at`、`can_revoke`、`items`、`next_cursor`，无额外字段。`schema_version` 恒为 `enterprise-discovery-schedule-management/v1`；`environment_id` 回声请求中的环境 ID；`evaluated_at` 为服务端评估时间（UTC Z）。

`cursor` 为上一页返回的 `next_cursor`（格式 `eds-` 加 32 位小写十六进制，即计划 ID 格式）；`limit` 默认 20、范围 1..100。按计划 ID 严格升序，取 `limit+1` 判断下一页；`next_cursor` 为本页最后一项的计划 ID，无下一页时为 `null`。空列表 `items=[]`、`next_cursor=null`。不提供全量统计、筛选、导出或详情 API，不自动拉取全部页。

## can_revoke 语义

`can_revoke` 仅由当前身份同时持有 `env:manage` 与 `edge:manage` 派生，不按角色名推断。它只是 UI 提示：不替代撤销 POST 的实时鉴权，不能作为撤销必然成功的承诺；即使为 true，撤销仍可能因 revision 冲突（409）或权限变化（403）失败。

## 条目字段（白名单）

每项精确包含 11 个字段，无额外字段，不使用 ORM 整行序列化：

| 字段 | 来源 |
| --- | --- |
| `schedule_id` | 记录主键（`eds-` + 32 位小写 hex） |
| `edge_agent_id` | 计划绑定的设备记录 ID |
| `status` | 存储状态，仅 `pending_confirmation`/`active`/`paused`/`revoked` |
| `revision` | CAS 版本，非负整数 |
| `starts_at` | 计划窗口开始（UTC Z） |
| `expires_at` | 计划窗口截止（UTC Z） |
| `interval_seconds` | 轮询间隔秒数 |
| `max_runs` | 预算上限轮次 |
| `reserved_runs` | 已预约轮次（含后续失败轮次；不是成功扫描次数） |
| `last_reserved_slot` | 最后预约槽号或 `null` |
| `created_at` | 记录创建时间（UTC Z） |

不返回 installation_plan、intent 原文、根目录、确认签名、凭据、tenant_id、设备种子或任何敏感配置。时间已过期与预算耗尽是消费方可自行解释的事实，服务端不回写存储 status。

## 消费边界

客户端必须严格验证版本、字段、环境回声、ID、日期、计数、cursor 与升序，异常响应报错，不回退为空列表或零值；未知 status 不显示为 active。窗口未开始/已过期用服务端 `evaluated_at` 判断，不用前端时钟，不推算「下次必定扫描时间」。`max_runs - reserved_runs` 仅解释为未预约预算，实际调度还受期限、设备状态与其他门禁约束。`active` 只表示计划已确认，不代表设备在线、采集成功或防护生效。撤销走既有 POST `/api/v1/environments/{environment_id}/discovery-schedules/{schedule_id}/revoke`，载荷严格 `{expected_revision}`。
