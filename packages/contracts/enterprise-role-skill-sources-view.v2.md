# Hermes 本地布局与技能安装来源对照 v2

同一 GET `/api/v1/agents/{asset_id}/skill-installation-sources`，Hermes 资产返回 enterprise-role-skill-sources-view/v2，OpenClaw 仍返回 v1。权限、认证租户、分页、同设备签名安装批次及范围核验、no-store 与只读语义全部沿用 v1。旧严格客户端可能拒绝 v2，生产者和消费者须配套交付。

顶层字段与 v1 相同，包括保留兼容字段名 declared_roots；在 v2 中该字段表示 roots/v2 的布局候选，不表示配置显式声明。历史来源必须为 source-view/v2、framework=hermes，目录必须为 roots/v2、basis=hermes_profile_layout、status=layout_candidate、唯一 profile_skills 根。缺少或错配为 source_unavailable，declared_roots=null、items=[]、next_cursor=null，不回退 OpenClaw 语义。

status=historical_comparison 时，只比较 profile 本地 skills 路径候选与同设备已签名安装观察的祖先目录摘要。匹配仍叫 historical_source_match；兼容字段值 outside_declared_sources 在 v2 中仅表示不在本次 profile 本地布局候选内，不是不可使用、未安装或被禁止。其他来源、优先级、启用/加载与权限没有由匹配证明。

两侧保留各自观察时间，runtime_status=unverified、effective_permissions=null；配置和安装观察可能不同步。配置路径本身未被枚举或解析链接，候选关系不证明运行时选用了该路径。external_dirs 和受信任项目来源不在本版本覆盖集合内。无新增扫描、授权、注册、运行绑定、写 API 或数据库迁移。

历史快照接口独立升级见 [configuration-history/v2](enterprise-role-configuration-history.v2.md)，不把当前来源对照称为历史配置重建。
