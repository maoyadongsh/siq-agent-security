# 旧配置快照与最新技能观察对照 v2（Hermes profile 本地布局）

同一 GET `/api/v1/agents/{asset_id}/configuration-observations/{observation_id}/skill-installation-sources`，Hermes 资产返回 enterprise-role-skill-snapshot-comparison/v2，OpenClaw 仍返回 v1。先定位（404）后 agent:read/env:read（403）、认证租户、no-store、只读语义与分页规则全部沿用 v1。旧严格客户端可能拒绝 v2，生产者和消费者须配套交付。

顶层字段与 v1 相同，包括 `configuration_observation`、`comparison_basis`、`coverage`、`items`、`next_cursor`、`runtime_status`、`effective_permissions`。`runtime_status=unverified`、`effective_permissions=null` 在 v2 同样恒成立。

与 v1 的唯一语义差异在**快照根声明的可核对条件**：v2 要求快照内 `configuration.skill_source_roots` 为 roots/v2 且 status=`layout_candidate`（v1 要求 roots/v1 且 status=`declared`）。其余情形（快照不可读、根缺失、basis 或 status 不匹配）一律 `status=snapshot_unavailable`、`items=[]`、`next_cursor=null`，**不回退 OpenClaw 语义，不静默改选其他快照**。核对通过时 `status=historical_comparison`。

匹配仍叫 `historical_source_match`；兼容字段值 `outside_declared_sources` 在 v2 中仅表示不在本次 profile 本地布局候选内，**不是不可使用、未安装或被禁止**。`declared` 一词在 v2 不出现为有效根状态，不得把 `layout_candidate` 解释为配置显式 allowlist。

技能列表分页与验签/完整观察匹配共用 enterprise-role-skill-sources-view/v2 的规则：cursor 为安装 ID、limit 1–100、默认 50；每个安装位置必须匹配同设备同一签名批次的观察，多份或缺失回执不构成已核验，不取无界结果的首片。

返回的技能观察是该快照设备各安装位置的最新已记录观察，**不是配置时刻的安装还原**；两侧时间都应展示，不推断过去/现在加载或权限。配置路径本身未被枚举或解析链接，候选关系不证明运行时选用了该路径。

GET 不创建运行绑定、扫描、权限、审计或其他业务写入，无新增数据库迁移。external_dirs 与受信任项目来源不在本版本覆盖集合内。

本版本只定义读取投影；采集与入库语义见 [role-skill-roots/v2](enterprise-role-skill-roots.v2.md) 与 [framework-source/v2](enterprise-framework-source.v2.md)，最新来源对照见 [role-skill-sources-view/v2](enterprise-role-skill-sources-view.v2.md)。
