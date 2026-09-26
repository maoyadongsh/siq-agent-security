# 企业环境清单分页 v1

既有 GET `/api/v1/environments` 保持 JSON 数组和 `env:read` 权限，tenant 仅来自验证身份。
未提供 limit 时保留原全量返回；提供 limit（1–200）时使用已有 X-SIQ 列表头协议分页。
排序为环境 name、id 升序，cursor 是前页末条环境 ID，须与 limit 一起使用。
cursor 必须非空且不超过 64 字符；不存在或无法按当前租户定位，统一 422
`environment_list_cursor_unavailable`，不透露其他租户信息。

返回 X-SIQ-List-Limit、X-SIQ-List-Returned、X-SIQ-List-Truncated；截断时返回
X-SIQ-Next-Cursor。include_total=true 时按租户计算完整匹配数，不受 cursor 影响。
Cache-Control: no-store。GET 不新增审计、outbox 或状态写入。

分页不是数据库快照：页面之间环境创建、重命名或删除可能影响结果；游标锚点被删除
应显式重新刷新，不自动猜测下一页。旧客户端未发送 limit 时不引入默认截断。
新增参数和元数据不改变原数组字段、安装/注册授权或业务权限。
