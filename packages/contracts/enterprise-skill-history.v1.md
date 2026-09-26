# 企业技能历史观察只读视图 v1

GET /api/v1/skill-installations/{id}/observations 返回
{schema_version: enterprise-skill-history/v1, installation_id, items, next_cursor}。
先按已认证租户及设备环境定位安装记录（404），再验证 agent:read 与 env:read（403）。
设备已吊销不删除历史；跨租户或损坏的设备来源关系不可见。响应 no-store。

items 使用技能清单 latest_observation 的相同字段，但每项仅代表其 observed_at 时刻
的历史记录；声明权限、manifest 摘要不证明完整安装包、当前安装、角色归属或有效权限。
不返回批次签名、原始文件路径、正文或凭据，不发起扫描或任何业务写操作。

limit 默认 50、范围 1–200。按 observed_at 倒序、observation_id 倒序稳定排序，
cursor 为上页最后一项 observation_id；必须属于当前租户和当前安装记录，否则 404。
游标不接受客户端时间或租户覆盖。每页有界 SQL，空历史为 items=[]、next_cursor=null。
分页不是数据库快照：翻页期间新到且排序在游标前的观察需刷新第一页才能看到，
不得以历史翻页结果宣称全量实时盘点。只增加历史读取，不改变既有清单和详情响应。

Web 技能清单为每个安装记录提供原生 details 历史入口，展开才请求，关闭卸载历史
视图，重新展开从第一页刷新。分页失败保留先前数据并明确未完成；401/403/404 清空
历史显示。客户端验证安装 ID、字段、摘要、时间、倒序和游标边界，异常不能作为空
历史。历史仅在内存中，不新增存储或业务写请求；不生成角色归属、安装或生效结论。
