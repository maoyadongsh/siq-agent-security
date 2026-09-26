# 企业资产发现来源查询 v1

GET /api/v1/agents/{asset_id}/discovery-origin 为只读投影。先按已验证租户定位资产（404），再校验 agent:read 与 env:read（403）。不接受调用者提供设备/环境覆盖。

响应 schema_version=enterprise-discovery-origin/v1，包含 asset_id、status、environment、device、reported_framework、assigned_role、observations、observations_truncated。status 为 device_bound、legacy_unresolved 或 source_unavailable。环境/设备只能来自资产的服务端 discovery_scope 经租户校验的绑定；历史 legacy 不从证据猜测来源，缺失或异常外租户绑定不暴露目标信息。

observations 最多 200 项，只包含同设备/同环境且关联资产的不可变 observation_id、evidence_id、content_hash、observed_at；稳定 ID 可用于后续关系引用。设备 revoked 状态保留说明历史来源，不把它当成当前在线、保护生效或运行时绑定。reported_framework 仅为原候选报告，assigned_role 是资产上已填写的角色标签，均不是独立框架实例或 Skill 归属证明。此接口不修改纳管状态，不扫描、不授权、不输出私钥/设备凭据或证据原文。
