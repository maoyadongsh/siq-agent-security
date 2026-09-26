# Hermes profile 本地技能布局来源 v2

本增量用于 CL-03，保留 OpenClaw roots/v1 原语义，不把 Hermes toolsets 转换为技能。依据已检视 Hermes 源码 `hermes_constants.get_skills_dir()`，profile 的 HERMES_HOME 下 `skills` 是本地来源；external_dirs 与受信任项目来源另有规则，不属于本投影覆盖范围。

Hermes 候选可附加 `attributes.skill_source_roots`，严格 JSON 字符串、最多 2048 UTF-8 字节，精确字段 schema_version、basis、status、roots：

- schema_version=`enterprise-role-skill-roots/v2`
- basis=`hermes_profile_layout`
- status=`layout_candidate`
- roots 恰一项，精确字段 kind=`profile_skills`、locator_sha256=64 位小写 hex。

仅 POSIX 规范化绝对 profile 目录适用。摘要为 UTF-8 编码 `profile目录/skills` 的 SHA256，与 Linux Directory 技能祖先摘要路径编码相同。仅字符串拼接，不枚举/读取/创建技能目录，不跟随其链接、不执行技能或解析环境变量。不存在目录仍可有布局候选，不能解释为发现了安装。摘要不是匿名性保证。

生产者只在明确授权且完整读取 config.yaml、成功生成 framework-source/v2 后附加；截断、读取失败、SOUL-only 均不附加。缺失属性保留未知，不等于没有技能。

入库必须先通过原任务/签名/证据校验和 Hermes 来源 v2 校验，再要求 roots/v2 ↔ framework-source/v2 ↔ hermes/hermes_profile 严格配对；OpenClaw roots/v1 仅允许原 OpenClaw 配对。未知字段/重复键/未知版本/错 kind/错数量/非规范摘要固定 422 role_skill_roots_invalid，任何写入前拒绝。根目录摘要与来源由同一候选批签名绑定；后端不能从 profile 摘要反推路径，不宣称独立宿主证明。

`layout_candidate` 不是配置显式 allowlist 或完整加载根集合。external_dirs、项目目录、平台禁用规则、优先级、目录真实存在/安装/加载均未由此证明。不得升级为 declared 业务权限或 effective，不创建运行绑定。

本版本定义采集与入库。现有 role-skill-sources-view/v1 的 OpenClaw 读取对照保持不变；Hermes 使用独立 [role-skill-sources-view/v2](enterprise-role-skill-sources-view.v2.md) 对照同设备已签名安装观察，不能进入旧版工作区声明语义。缺失/错配仍返回不可用，不以同名推断关系。外部与项目来源、真实加载和历史快照的扩展不由此自动完成。
