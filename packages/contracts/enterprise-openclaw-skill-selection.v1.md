# OpenClaw 角色技能范围声明 v1

事实来源：[官方 skills 配置](https://docs.openclaw.ai/tools/skills-config)与[旧 list 布局的官方文档](https://docs.openclaw.ai/id/tools/skills)。技能 allowlist 是可见/加载筛选，不是 shell 授权边界；不证明安装或实际加载。关系声明不能升级为 effective。

采集支持 agents.list 数组及 agents.entries 对象，后者以键为明确 agent.id，按键排序；同时出现两种布局或 entries 中重复指定不一致 id 时拒绝。身份继续沿用 enterprise-openclaw-identity/v2，布局迁移同根同 ID 不换身份。默认角色扩展见 enterprise-openclaw-default-role/v1：仅成功读取且无显式 roster 时推导 main，带 config_default 来源标记；null/重复键/include 不得触发该推导。

候选 attributes.skill_selection 保存有界 JSON 字符串：{schema_version: enterprise-openclaw-skill-selection/v1, source: agent|defaults|none, status: declared_list|unconfigured|unsupported, names: string[]}。优先使用角色显式 skills（包括空数组），仅缺省时继承 agents.defaults.skills；null/畸形显式值不回退默认。未配置为 unconfigured；无法安全解析为 unsupported，names=[]，两者均不代表无技能。

合法 names 最多 64 个互异 ASCII 机器标识，每项最多 128 字节，通过既有敏感值脱敏检测且不被改写；按名称排序。非法/秘密形状/超限数组整项 unsupported，不保留部分关系。declared_list + 空数组才代表显式空范围；role 声明与原配置完整摘要的 evidence ID 同批引用，经既有设备签名上传验证。不读取任何技能文件或执行其内容，不按名字直接匹配安装记录。

本层仅采集声明。控制面追加观察历史和只读投影见 enterprise-role-skill-observations.v1.md；名称到精确安装位置解析、漂移和前端关系图仍需单独实现，不由声明自动推导。
