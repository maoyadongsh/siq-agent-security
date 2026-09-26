# 企业框架配置实例来源 v1

本增量建立设备内框架配置实例与角色的报告来源，不证明进程正在运行、技能已加载或任何权限已生效。第一生产者为 OpenClaw，其他框架没有该声明时保持未知，不按名称补造。

候选 attributes.framework_source 为不超过 2048 UTF-8 字节的严格 JSON 字符串，字段精确且全部必填：schema_version=enterprise-framework-source/v1、framework=openclaw、instance_key（64 位小写 SHA256）、config_sha256（配置内容 SHA256）、evidence_id（本候选引用的本批配置证据标识）。不携带原始目录、秘密或租户覆盖字段。

OpenClaw instance_key=SHA256(UTF-8 紧凑 JSON 数组 ["enterprise-openclaw-config-instance/v1", normalized_absolute_root])，序列化遵循当前 Go encoding/json 字符串编码。同配置根的多个角色共享实例标识，角色名称/配置内容变化不改变实例标识，不同配置根分开。作用域是认证租户+认证设备+framework+instance_key，禁止跨设备仅凭摘要混并。路径摘要不是匿名化或防猜测承诺，不作为访问授权依据。角色既有 v2 身份不变。

入站在签名/任务/设备校验后、任何证据或资产写入前检查：仅 openclaw 任务和 openclaw_agent 候选可声明；v2 候选 ID 与 locator 一致；证据 ID 在本候选引用和本批证据中唯一存在、类型 openclaw_config、subject_ref 指向该候选、内容摘要与声明一致。重复 JSON 键、多余字段、null、大小写别名和格式异常拒绝，错误正文不回显载荷。未带此字段的旧生产者兼容。服务端不能从摘要反推目录，校验的是认证设备报告的来源一致性，不是独立宿主证明。

当前阶段复用已签名候选属性保存最新报告；不声明已建立不可变框架实例历史或角色—技能精确关系。未来聚合/API 展示必须保留设备/租户作用域、证据和观察时间，旧记录未知；技能安装关联仍需独立位置/manifest 证据，不能按同名建立。

## 只读来源投影

GET /api/v1/agents/{asset_id}/framework-source：先认证租户内定位资产（404），再 agent:read 和 env:read（403），no-store。固定返回 schema_version=enterprise-framework-source-view/v1、asset_id、status、source、runtime_status=unverified、skill_relationship_status=unresolved、effective_permissions=null。未声明时 status=no_recorded_source；格式或设备/证据归属不一致时 status=source_unavailable；两者 source=null，不回显异常属性。

来源可核对时 status=historical_reported_source；source 仅含 framework、instance_key、environment_id、device_id、device_revoked、config_sha256、evidence_id、observation_id、observed_at。证据须在本资产引用集合中，匹配原候选 v2 ID、配置摘要、类型、认证租户及该设备环境/collector，唯一命中；缺失或多义不投影。设备吊销保留历史但显式标记。作用域由服务端真实关联提供，不接受客户端 tenant/device 覆盖。无原始路径、配置正文或签名。GET 不创建扫描、资产关系、权限或审计事件；该响应仅供来源呈现，不是运行实例、当前安装状态或独立宿主证明。

## 版本导航（2026-09-26）

本文件的 v1 OpenClaw 语义不变。Hermes 配置来源为附加版本：入库与读取投影均使用 v2，见 [enterprise-framework-source.v2.md](enterprise-framework-source.v2.md)；清单端点按页选择 `enterprise-framework-role-inventory/v1` 或 v2，见 [enterprise-framework-role-inventory.v2.md](enterprise-framework-role-inventory.v2.md)。消费者必须校验版本/框架配对，不接受任意框架名；本节不是"已全面支持"的声明，两条来源线的证据边界各自保留。
