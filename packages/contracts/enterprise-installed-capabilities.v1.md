# 企业已安装采集能力 v1

企业 setup-enterprise 主路径在可信发行验签暂存之后、设备注册之前探测所有选定采集器。只执行暂存目录内计划选定的 Connector 二进制，不执行被扫描配置、Skill 或钩子。仅调用 connector-protocol.v1 的 describe 和 validate_scope，不调用 collect/plan_scan。

每个 describe 的版本必须与计划相同，输出限制必须为正且不超过协议默认 8 MiB；对象和数据类别必须为有界机器标签。权限说明允许本机路径，但限长、拒绝控制字符且不上报。validate_scope 必须明确 valid=true 且无 errors。每个采集器最多 5 秒，每操作输出最多 64 KiB；任何缺失、不兼容、超时、拒绝范围或取消均在注册前停止，不签发新设备身份、不消耗注册码。固定错误不携带采集器原始诊断，暂存位置保留供恢复。

注册 capabilities 保留旧字段 connectors、protocol_version、data_categories，并增量携带 inventory_schema=enterprise-installed-capabilities/v1 与 connector_versions（id → 实测版本）。这些是设备申报，不是硬件证明、有效权限或策略生效证据。范围验证不证明运行时访问一定成功。

后续实现已接入统一服务心跳刷新和 scan 能力调度；探测失败撤回可用采集器。历史独立 register 仍保留兼容行为。新 Edge 实测报告升级为 [v2](enterprise-installed-capabilities.v2.md)，增加各采集器支持的任务类型；控制面继续接受 v1，但 v1 不支持领取新的 skill_scan。已注册身份不重新注册。UI 全采集器展示、自动技能任务签发及正式安装包验收仍未整体完成。
