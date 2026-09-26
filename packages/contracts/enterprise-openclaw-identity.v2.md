# 企业 OpenClaw 角色发现身份 v2

配置角色不是运行实例。角色 candidate_id = openclaw:v2: + SHA-256(JSON([规范绝对配置根目录, 原配置 agent.id]))，source_locator = openclaw://agents/v2/ + 同摘要。显示名称可重复或改名，不参与身份；相同 ID 在不同根目录不能合并。同一规范根仅扫描一次。控制面仍以认证租户和设备 discovery_scope 隔离。

默认角色扩展 enterprise-openclaw-default-role/v1 将无 roster 的安全配置推导为 main，使用相同身份算法并记录 config_default 来源；显式 main 与默认 main 保持一个位置身份。该扩展不是默认运行实例证明。

agent.id 必须非空、无首尾空白/控制字符、最多 128 UTF-8 字节；单配置重复 ID 或缺 ID 时整次采集拒绝，不用 name 猜测身份。证据 ID = ev:openclaw:v2: + SHA-256(JSON([角色位置摘要, 完整配置内容摘要]))，不能使用文本编码的前缀作为哈希。同位置配置变更保留角色身份并生成新证据；名称/模型/工作区变化不证明新的运行实例。

auth-profiles 元数据证据按根目录摘要隔离，只记文件名/大小、不读内容；必须被本根候选引用，无本根候选时不生成孤立证据。所有权限事实仍仅 declared，不创建有效权限或技能归属。旧 v1 资产不会按名称自动合并到 v2，旧历史保留，归属迁移须另行审阅。
