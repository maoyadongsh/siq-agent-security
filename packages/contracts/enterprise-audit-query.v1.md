# 企业审计精确查询 v1

GET /api/v1/audit-events 的查询能力合同（ENT-019-AUDIT-QUERY 子任务）。本合同只定义审计事件的**只读精确查询**增强；它不声称后端已实现完整的资产→策略→执行审计关联图，也不定义任何审计写入、导出、删除或修改能力。

## 1. 路径、方法、权限与租户边界

- 路径与方法：`GET /api/v1/audit-events`，响应体为 `AuditEventOut` 数组，字段不变。
- 权限：调用方身份必须具备 `audit:read`，否则统一 403。
- 租户边界：`tenant_id` 只从验证后的身份派生，永远作为过滤谓词的一部分；本接口不提供也不接受任何租户覆盖参数。不同租户中相同的 `request_id`/`resource_id` 值互不混并，各自只命中本租户记录。

## 2. 查询参数

既有参数（行为不变）：`actor_id`、`action`、`resource_type`、`cursor`、`limit`、`include_total`。

新增四个可选精确过滤参数，非空值与数据库字段严格相等比较：

| 参数 | 匹配字段 | 最大长度 |
| --- | --- | --- |
| `request_id` | `AuditEvent.request_id` | 64 |
| `resource_id` | `AuditEvent.resource_id` | 64 |
| `actor_type` | `AuditEvent.actor_type` | 16 |
| `decision` | `AuditEvent.decision` | 16 |

最大长度以当前模型字段定义为准。`actor_type`、`decision` 不限定为前端当前已知枚举：合法长度内的未知原值（例如未来新增的操作者类型或决策值）允许查询并按原值精确匹配。

示例：

```text
GET /api/v1/audit-events?request_id=req-example
GET /api/v1/audit-events?resource_type=change_request&resource_id=chg-example
GET /api/v1/audit-events?actor_type=edge&decision=deny
```

## 3. 匹配语义

- 全部为精确相等匹配；不使用模糊匹配、前缀/子串匹配或动态 SQL 字符串拼接。含引号、SQL 片段、HTML 等形态的参数值仅作为查询数据参与相等比较，不被执行，也不扩大结果集。
- 所有新旧过滤条件之间为 AND 组合，并与租户谓词一起生效。
- 不静默截断、不修改查询值；不使用 `.strip()`、大小写转换等改变精确匹配含义的操作。

## 4. 缺省、空值与超长

- 参数缺省：不添加该项过滤，行为与旧版本一致。
- 空字符串（如 `?request_id=`）：返回 422，避免调用方误以为执行了精确过滤、实际却查询全部。
- 超过最大长度：返回 422。
- 旧参数（`actor_id`、`action`、`resource_type`、`cursor`、`limit`、`include_total`）的既有兼容行为不变，本合同不为其新增校验。

## 5. 分页与总数口径

- 排序、`cursor` 格式（`<created_at_iso>|<event_id>`）、`limit` 上限（默认 50、硬上限 200）、响应头（`X-SIQ-List-Limit/Returned/Truncated`、`X-SIQ-Next-Cursor`、`X-SIQ-List-Total`）与响应结构均保持现有协议；旧 cursor 兼容行为不变。
- 列表查询与 `include_total=true` 的总数查询使用同一组过滤条件（租户 + 全部新旧过滤参数）。
- 总数不受当前 `cursor` 影响：后续页请求 `include_total=true` 时，总数仍是全部匹配记录数，而非剩余条数。
- 新参数参与的多页查询不得漏项、重复或跨租户；同一时间戳的多条记录按既有 `(created_at desc, id asc)` 次序稳定分页。

## 6. 响应语义

- 200：成功，返回本页事件数组与列表元数据头；无匹配时返回空数组，`include_total=true` 时总数为 0。
- 403：身份缺少 `audit:read` 权限；无权限调用方不能通过过滤参数获得任何审计事件或总数。
- 422：新增参数为空字符串或超过最大长度。
- 审计 `summary` 字段维持既有脱敏语义，本合同不新增 summary 全文搜索或原始内容搜索。

## 7. 只读与证明边界

- 本查询只读，不产生任何业务状态变更，不写入审计、outbox 或被查询的业务对象。
- 关联标识不构成执行成功或保护效果的证明：`decision=allow` 不解释为策略已生效或安全防御已验证；同一 `request_id` 下的事件仅表示可用于关联查询，不自动证明完整调用链、因果关系或执行效果。

## 8. 兼容范围与不做事项

- 兼容：既有客户端不传新参数时行为完全不变；响应仍使用现有 `AuditEventOut`，不暴露内部数据库字段。
- 不做：不新增审计写入接口、导出/下载/删除/修改接口、summary 或原文搜索、租户覆盖参数；不修改 cursor 解析与错误处理机制；不修改模型、schema、迁移及前端。
