# 原生技能采集 v1

Directory Connector 新增 collect_skills 操作，输入与 collect 相同的 {plan}，输出独立 schema_version=enterprise-skill-collection/v1、observations、issues、truncated，不产生 AgentCandidate/Evidence/PermissionFact。旧 collect 行为不变。

当前只在 Linux 支持并在 describe.objects 声明 skill_manifest；其他平台返回 unsupported。scope 必须显式给出 1–16 个绝对目录（可展开 ~/），include 精确为 [SKILL.md]，不支持通配根、exclude、空范围或系统宽根。按原有 ValidateScopeSafety 再检查。不会从目录名推断框架或角色关系。

Linux 从根文件描述符逐级 openat + O_NOFOLLOW 定位授权目录，枚举与递归都基于已打开目录描述符；拒绝符号链接根和子目录，不沿字符串路径重新打开已枚举文件。只读取精确名 SKILL.md 的普通文件；其余文件包括 .env 不读取。隐藏子目录、node_modules、vendor 不递归。深度最多 32、访问条目最多 10,000、清单最多 200、总字节不超过计划上限（最高 16 MiB），采用有界分批目录枚举并遵守操作超时。

清单最多 256 KiB，超过限额/剩余预算不产生完整摘要，issues 仅携带位置摘要和固定机器状态；truncated 表示结果不完整。读前后大小/修改时间变化拒绝观察；不声称抵御特权攻击者任意修改内核或伪造元数据。清单解析失败仍可返回完整内容摘要与失败状态，不输出正文/description/未知元数据。

observations 对齐 enterprise-skill-upload/v1 的观察字段，位置摘要来自规范化绝对安装目录。同一位置的重叠根去重，相同名称不同位置独立。此操作没有凭据、不上传、不联网、不执行内容；Edge 任务调度、已确认范围校验、签名上传和回执仍须接通，不能单凭此操作宣称自动盘点完成。

版本导航：本 v1 只描述 v1 线路。**`enterprise-skill-collection/v2` 不另建文件**，完整定义见 [enterprise-skill-ancestry/v2](enterprise-skill-ancestry.v2.md)：Linux Directory 新增 `describe.objects=skill_manifest_ancestry_v2` 与 `collect_skills_v2` 操作，返回 collection/v2；Edge 仅在采集器显式声明新能力时调用 v2，否则继续 v1；旧 Edge 不受影响。生产者见 `connectors/directory/skills_linux.go` 与 `edge/agent/skill_upload.go`。跨文件名建档关系另由 `scripts/enterprise-experience/contract-version-aliases.json` 显式登记。
