# Hermes 历史配置与技能观察对照 v2

现有 configuration-observations 与 configuration-observations/{observation_id}/skill-installation-sources URL 不变。Hermes 资产分别返回 enterprise-role-configuration-history/v2 与 enterprise-role-skill-snapshot-comparison/v2；OpenClaw 保留各自 v1。所有顶层字段、分页、只读、认证租户与对象 404/双读权限 403、no-store 保持原合同。

已记录的 Hermes 配置为 framework-source/v2，roots 可缺失或为 roots/v2 的单一本地 layout_candidate。必须与原任务 connector=hermes、设备目标、保存批摘要及所属资产框架配对。OpenClaw 则仍要求 source/v1 与 roots/v1。错配的历史行投影为 snapshot_unavailable、configuration=null，不回退最新属性。

来源对照基于用户明确选中的不可变配置快照，和当前分页内最新的同设备签名技能安装观察；不是重建历史时刻安装状态。Hermes 布局候选状态及 profile_skills 语义沿用 role-skill-sources-view/v2，仅提供位置关系，不证明启用、加载、优先级或权限。缺失 roots 无法比较；保留 unverified/null 和双方时间。

前端同时支持两版并逐行校验来源/根/框架配对，外层 v1 不接受 Hermes 快照，v2 不接受 OpenClaw 成功快照；不可核对行不含配置。旧严格客户端可能拒绝新版本，须配套交付。无新增任务、业务授权或数据库迁移。
