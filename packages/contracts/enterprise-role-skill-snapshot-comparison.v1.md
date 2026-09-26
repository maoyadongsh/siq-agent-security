# 旧配置快照与最新技能观察对照 v1

GET /api/v1/agents/{asset_id}/configuration-observations/{observation_id}/skill-installation-sources。独立响应版本，不改变原最新来源端点。先在认证租户定位资产和该资产可读设备/环境/任务范围内的观察（404），再 agent:read/env:read（403）；no-store。

响应 schema_version=enterprise-role-skill-snapshot-comparison/v1、asset_id、configuration_observation（沿用历史 API 的单项快照结构）、status、comparison_basis=latest_skill_observations_against_saved_configuration、coverage=page_of_device_installations、items、next_cursor、runtime_status=unverified、effective_permissions=null。

配置使用显式选择快照的根声明和设备，不用最新资产属性替换。可核对且有 declared 根时 status=historical_comparison，否则 snapshot_unavailable，items=[]、next_cursor=null，不静默选择其他快照。返回的技能观察是该快照设备各安装位置的最新已记录观察，不是配置时刻的安装还原；两侧时间都应展示，不推断过去/现在加载或权限。技能列表分页与验签/完整观察匹配共用 enterprise-role-skill-sources-view/v1 的规则，cursor 为安装 ID、limit 1–100、默认 50。

快照记录本身不是完整原批重新验签证明；设备吊销仅保留历史标记。GET 不创建运行绑定、扫描、权限、审计或其他业务写入。原有最新来源 UI/响应继续兼容；新快照选择界面另行实现。

版本导航：本 v1 仅适用于 OpenClaw 资产（根声明 status=`declared`）。Hermes 资产同一端点返回 [snapshot-comparison/v2](enterprise-role-skill-snapshot-comparison.v2.md)，其根声明要求 roots/v2 的 `layout_candidate`；两者字段相同、可核对条件不同，不得互相套用。
