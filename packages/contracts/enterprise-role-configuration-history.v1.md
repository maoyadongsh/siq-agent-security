# 角色配置来源观察历史 v1

已通过签名、设备/任务、framework_source 和 skill_source_roots 校验的候选批，在原有资产/证据/审计事务内追加 role_configuration_observation。只有本批明确带 framework_source 的候选会生成观察；不从已有资产最新属性回填历史，也不为旧生产者补造观察。

字段：id、tenant_id、asset_id、edge_agent_id、task_id、batch_digest、framework_source（严格解析后的目录实例/配置摘要/证据 ID）、skill_source_roots（严格解析后的目录声明，可 null）、observed_at（本候选引用配置证据的观察时间）、received_at（服务端接收时间）。无原始路径、配置正文或密钥。认证租户+资产联合外键、设备/任务外键、asset_id+task_id 唯一约束。若批内资产来源重复且存在配置声明，写入前拒绝；同一上传重放不追加，不同任务即使相同配置也保存各自观察。

后续属性更新不改写旧观察，服务不提供观察更新/删除接口；这不是数据库管理员不可篡改承诺。记录 batch_digest 作为已验签批次关联，未保存完整候选批原文，因此不能只用本表独立重建原批验签，不声称具有完整批签名回放能力。新表不能自动赋予来源更多可信度、技能加载或 effective 权限。

迁移 0027 从 0026 创建新表和索引，不回填；空表可降级，有观察时拒绝降级删除。生产迁移必须另行授权，本次仅隔离数据库验证。历史查询见下文，按历史快照对照技能来源仍待单独实现；现有最新来源 API 本增量不改变。

## 只读历史查询

GET /api/v1/agents/{asset_id}/configuration-observations。认证租户内先定位资产（404），再检查 agent:read/env:read（403）；no-store。limit 1–100，默认 50；cursor 为 rco_ 观察 ID，在本资产/租户及可核对的设备环境/任务范围内定位，否则 404。按 received_at 降序、id 降序稳定分页；不宣称跨请求数据库快照隔离。

响应 schema_version=enterprise-role-configuration-history/v1、asset_id、coverage=recorded_configuration_observations、items、next_cursor、runtime_status=unverified、effective_permissions=null。空数组只表示无可读历史快照，不证明角色/技能未安装。

items 含 observation_id、observed_at、received_at、environment_id、device_id、device_revoked、status 和 configuration。status=recorded_snapshot 时 configuration 含 framework_source、skill_source_roots（可 null）、task_id、batch_digest；source/roots 在读取时重新按严格结构校验，并核对 task 批摘要及 OpenClaw 来源。结构/关联损坏时 status=snapshot_unavailable、configuration=null，不回显异常字段。跨租户或无法核对设备/任务环境的记录不进入结果。

历史记录使用快照保存的声明，不读取最新资产属性替换旧值；设备吊销显式标记，不删除历史。不输出私钥、原始路径、配置正文或批签名；已保存快照不是重新验签证明，配置与技能的旧快照对照尚未由此接口实现。GET 不写审计/业务状态。
