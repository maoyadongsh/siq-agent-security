# 角色与技能安装来源对照 v1

GET /api/v1/agents/{asset_id}/skill-installation-sources，认证租户内先定位资产（404），后 agent:read/env:read（403），Cache-Control: no-store。cursor 为 ski_ 安装 ID，limit 1–100，默认 50。无业务写入。

响应 schema_version=enterprise-role-skill-sources-view/v1、asset_id、status、framework_source、declared_roots、coverage=page_of_device_installations、items、next_cursor、runtime_status=unverified、effective_permissions=null。配置来源或目录声明缺失/无效/未解析时 status=source_unavailable，declared_roots=null、items=[]；这不是零安装。正常 status=historical_comparison。

在已核对配置证据的同租户/设备内按安装 ID 分页，使用每个位置最新观察（时间降序、ID 降序）。不预过滤匹配结果，避免忽略旧版本/缺证据安装，也避免匹配少时隐藏下一页。每项 installation_id、locator_sha256、relationship_status、matched_sources、observation。合法签名 v2 链包含声明目录时 historical_source_match，否则 outside_declared_sources；后者仅指这两个已声明工作区来源，不是与角色无关或不可使用。旧 v1、缺失或损坏证据为 unresolved。失败时 observation=null，不回显不可信元数据。

读取时核对回执租户/设备、task 身份/环境/目标设备/范围摘要、batch 摘要、设备公钥签名、严格上传 schema，以及观察的安装位置、manifest 摘要、解析字段、时间、批签名与签名原文一致。回执每批只解析一次，签名原文最大 2 MiB；本页最多 100 个不同批次。回执缺失/歧义/超限失败关闭，不回退旧观察制造匹配。历史已吊销设备可呈现历史比较，但 framework_source 显式携带吊销标记。到期任务不抹除历史证据。

declared_roots 是角色最新保存的配置声明，并非不可变的角色配置快照；framework_source 与 observation 各自有观察时间，可能不同步。historical_source_match 只证明两份报告的位置关系，不证明目录当前存在、技能曾被该角色加载、允许列表/优先级裁决、完整包摘要或 effective 权限。配置来源的既有 API 保持原语义。没有自动创建业务权限或运行绑定。
