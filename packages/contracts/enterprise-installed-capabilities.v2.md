# 企业已安装采集能力 v2

继承 v1 字段与验签/范围/限长要求，inventory_schema 改为 enterprise-installed-capabilities/v2，必需 connector_task_types（每个已测 connector ID → 非空、无重复的 scan / skill_scan 数组）。键集合必须精确等于 connectors；skill_scan 目前仅 directory 可声明。Edge 只有 describe 返回 skill_manifest 且 network_access=false 时才增加 skill_scan，其他采集器保持 scan。声明是设备报告，不是授权或可信硬件证明。

控制面继续接受 v1；v1 和 legacy 不具备新技能任务能力。技能 pending 任务只允许新鲜且有效的 v2 技能能力设备领取，必须 connector=directory、inventory_kind=skills、精确目标设备；过滤在 LIMIT 和原子租约更新两处生效。缺失/错误/过期/未来心跳拒绝新任务。普通 scan 保留原兼容行为。

已 uploaded 的技能任务允许原 lease_owner 在能力撤回后恢复最终回执，但仍需精确目标、环境、在线设备身份和任务期限；不允许另一设备接管。Edge 每次恢复继续验证确认计划和原日志签名，不能据此重新采集或授予权限。
