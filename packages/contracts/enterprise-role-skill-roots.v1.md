# 角色技能来源目录声明 v1

本合同是 ENT-008/009 精确位置关联的第一段证据，不是最终安装关系。OpenClaw 候选可携带 attributes.skill_source_roots（严格 JSON 字符串，最多 2048 UTF-8 字节），必须同时携带并通过 enterprise-framework-source/v1 校验。两项属性由同一候选批签名绑定，来源为该角色的完整配置证据。

精确字段：schema_version=enterprise-role-skill-roots/v1、basis、status、roots。basis 为 agent_workspace、default_workspace 或 none；status 为 declared、unresolved。roots 是最多两项的数组，每项精确含 kind 和 locator_sha256。kind 为 workspace_skills 或 project_agent_skills，摘要为规范化绝对目录 UTF-8 字节 SHA256，与 Directory 安装位置摘要的路径编码一致；路径摘要不保证匿名。

当前生产者只处理角色明确配置的 POSIX 绝对 workspace，以及已由默认角色逻辑继承的 defaults.workspace。未配置、相对路径、波浪号、变量引用、控制字符、反斜线、通配或超过 4096 字节的路径均 unresolved，roots=[]；未配置 basis=none，其他情况保留其声明来源。禁止使用采集进程 cwd、HOME 或猜测配置根补全。declared 时输出按固定顺序排列的 workspace/skills 与 workspace/.agents/skills 两个目录摘要，basis 不得为 none。

只进行字符串规范化与摘要，不读取、创建或扫描 workspace，不增加安装授权范围，不声称目录存在。未带字段的旧生产者兼容；带字段但缺少有效 framework_source、未知字段、重复键、重复/错序 kind、非法摘要、状态不一致均 422 role_skill_roots_invalid，写入前拒绝。

后续关联必须同时具有认证租户/设备作用域、配置来源以及技能采集给出的精确目录包含关系和完整清单观察；不能从名称拼接路径或仅凭摘要相等推断加载。共享来源、多层技能目录、相对路径/变量解析、其他加载层和版本特定优先级仍需单独实现。当前不改变 framework-source API 的 skill_relationship_status=unresolved，不生成 PermissionFact/effective 或运行时绑定。

参考：[OpenClaw Skills](https://docs.openclaw.ai/tools/skills)（2026-09-25 核对）。官方说明工作区存在上述两个技能来源，且加载还有共享等其他层；本字段不代表完整加载目录集合或加载优先级裁决。
