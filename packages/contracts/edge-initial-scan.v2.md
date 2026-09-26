# 已确认安装计划首扫 v2

同一路由 POST /edge/v1/initial-scan，schema_version=edge-initial-scan/v2。继承 v1 的原计划审计匹配、首次期限、身份、签名、事务、配额和设备级幂等要求；普通采集任务保留。若计划选择 directory 且 include 显式含 SKILL.md，额外签发一个 skill_scan，scope roots 完全来自该计划，include 精确缩小为 [SKILL.md]，inventory_kind=skills，目标绑定当前设备。最多 16 个字面根目录，拒绝 glob；不自动扩大目录或读取其他用户配置。

技能任务必需新鲜 v2 实测技能能力。缺失能力时整批拒绝，不先保存普通任务再静默丢失技能盘点。普通和技能 pending 均计入初扫配额；首扫记录、全部任务签名、审计、outbox 同事务。技能任务事件为 skill.scan.created.v1，不代表已发现或批准权限。

Directory 的普通扫描排除已经交给独立技能采集的 SKILL.md，避免把技能文件再作为智能体候选；若范围仅有 SKILL.md，则只创建技能任务。响应 schema_version=edge-initial-scan-result/v2，其余字段与 v1 相同；任务数等于实际普通任务数加技能任务数。已有首次记录必须匹配本版本任务类型和数量，否则返回 initial_scan_version_conflict，不覆盖历史记录或假称已补技能任务。存量设备升级补扫另行实施；新安装 Edge 在明确选择技能范围时使用 v2，其余仍使用 v1。重复同计划同任务集合返回原编号，不重新签发。
