# 企业技能清单只读视图 v1

GET /api/v1/skill-installations 返回 {schema_version: enterprise-skill-inventory/v1, items, next_cursor}。要求 agent:read 和 env:read，租户来自认证身份。支持 environment_id、device_id 精确过滤；limit 默认 50、1–200，cursor 为上页末尾 installation ID，按 ID 升序；客户端 tenant_id 不参与查询、不能覆盖身份。不存在的过滤结果是空清单，不等于环境已扫描且没有技能。

GET /api/v1/skill-installations/{id} 返回同一条目；先按租户定位（404），后查权限（403）。缓存 no-store。来源关联同时验证 installation 租户和设备环境租户，损坏的跨租户来源不泄漏；清单排除该条目，详情返回 404。

条目包含 installation_id、locator_sha256、环境 id/name、设备 id/identity/revoked、presence=observed_not_verified_current、relationship_status=unresolved、effective_permissions=null。latest_observation 可为 null，否则包含 observation_id、manifest_sha256、parser_version、parse_status、name、allowed_tools_present、declared_tools、observed_at、batch_digest。最新指 observed_at 最大（同时间按 observation ID 倒序），不是当前仍安装、已安全、已启用或权限已生效的证明。无角色关系证据时不推断归属；未解析/未声明不能视为无权限。

响应不包含原始路径、正文、凭据、设备密钥或批次签名；manifest 摘要不是完整安装包摘要。每页使用有界 SQL 查询，不逐条查询历史或加载全部观察。此只读接口不生成 grant、策略、审批、变更或扫描任务。

历史版本读取见 [enterprise-skill-history/v1](enterprise-skill-history.v1.md)：
GET /api/v1/skill-installations/{id}/observations。此增量不改变既有 latest_observation 的语义。
