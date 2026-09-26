# 企业角色技能范围观察 v1

OpenClaw 的 enterprise-openclaw-skill-selection/v1 声明经已有设备批次签名、证据签名、租户/任务/引用校验后，追加 RoleSkillSelectionObservation。身份为租户内资产 + 上传任务，一任务一资产最多一条；同任务原批次重放沿用原结果，不能改写历史。字段含设备、任务、批次摘要、服务端接收时间、候选观察时间、范围声明和本批来源证据 ID/摘要/观察时间快照。批次摘要说明入站已验证来源，并非凭这一摘要就能离线重验整个签名。

仅接受 openclaw / openclaw_agent 来源、openclaw 扫描任务、v2 哈希定位和身份一致的候选。声明 JSON 最多 10000 UTF-8 字节，每个角色 1–64 个互异的本批证据引用。声明仅支持原合同规定的版本/来源/状态/互异排序名称；额外字段、重复 JSON 键、非法或敏感名称、不一致状态、缺证据、重复资产定位或证据 ID 拒绝整个批次，错误不回显输入。旧客户端没有该字段时继续兼容，但不从旧属性回填关系历史。新观察不等于当前安装、加载或权限生效。

迁移 0023 增加租户/资产复合引用及观察表，禁止非空降级。应用只提供追加路径，无修改/删除历史 API；这不宣称数据库管理员不可篡改。

GET /api/v1/agents/{asset_id}/skill-selections：先租户定位 404，再 agent:read 和 env:read；no-store。返回 enterprise-role-skill-observations/v1、asset_id、relationship_status=unresolved、effective_permissions=null、按接收时间/ID 降序最多 100 条 observations 和 observations_truncated。设备/环境仍须属于当前租户；无法验证来源的记录不投影。只返回规范范围、摘要/证据 ID 与设备是否吊销，不暴露路径、签名或原始配置。空记录明确为 no_recorded_declaration，不等于零技能；非空为 historical_declarations。安装位置解析、漂移裁决和权限变更不由此接口执行。
