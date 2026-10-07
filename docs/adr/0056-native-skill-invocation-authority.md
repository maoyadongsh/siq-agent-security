# ADR-056：原生 Skill 调用上下文与双重授权

日期：2026-10-07。状态：接受设计，分阶段实施；对应 OPT-08，最终效果由 OPT-10 验收。组件合同存在不表示日常入口已完成接入。

## 已核对的问题

现行 SEC v1 要求 runtime identity、session binding 和已安装 Skill 使用同一 Grant。`receipt.Engine` 也拒绝 Intent 所选 Grant 与 SEC Grant 不同。该限制正确保护既有协议，但不能通过删除比较来支持同一 Agent 的多个不同 Skill Grant。

历史业务验收通过 `research_skill_sync.py` 与宿主轮询器，依据显式测评选择加载真实 Skill、签发 SEC。它不是产品级自动归属。工作区新版 Hermes 的 `on_skill_lifecycle` 属于 best-effort 遥测，重复加载还可能走缓存；该事件本身不能成为执行授权证据。业务镜像使用固定版本/补丁，不能用工作区最新版的接口推断它已经支持新协议。

## 决定

1. 保留 SEC v1 的签名字节、读取与单 Grant 不变量。新增 `skill-execution-context/v2`，使用独立持久目录，记录 Agent Grant、Skill Grant、精确安装、原生加载事实及父调用上下文；v1 读取器不得误读 v2。
2. Agent 的运行身份和 Intent 继续绑定原 Agent baseline Grant，不因 Skill 切换重新签发身份。Skill Grant 来自管理员已批准的安装，必须属于同一 Agent/实例。有效权限为精确 Agent baseline ∩ 当前 Skill ∩ 所有活动父调用的权限；不选择“最新的另一个 baseline”替换绑定。
3. `loader` 摘要是可信宿主验证加载来源后的签名记录，不是模型自报字段。宿主必须核对实际原生加载文件、只读安装目录、安装记录和运行制品。SDK best-effort 观察事件或模型消息中的 skill 名称不足以签发。
4. 真实工具调用另需宿主提交精确 call binding，覆盖原生 session/task、调用 ID、最终工具名及参数摘要；服务端按完整调用查找。不允许模型通过传 context ID、Skill claim 或省略字段选取更宽权限。注册为调用级受管的会话缺少记录时 hard deny，不能回退普通 Agent 授权。
5. 同一原生任务里的嵌套加载与切换保留权限祖先约束，不能通过加载 Writer 洗掉 Reader 限制。新的独立用户任务可从原 baseline 开始；结束边界必须来自可信宿主，不从模型文字猜测。并行调用具有独立调用 ID 和父链，拒绝跨调用借权。
6. 无 Skill 时由可信宿主明确记录无技能调用并使用 baseline；未知、混杂、未观测加载或不可确定的父链拒绝。保留“运行上下文归属”和“模型思想/指令因果归属”的区别，不宣称能够证明后者。
7. 签发、调用绑定与每次执行重新检查 identity/session、Agent Grant、Skill Grant、安装内容、祖先、任务生命周期、撤销与租约。签名有效不能代替这些活体检查。加载记录、SEC、调用绑定和撤销只追加，私钥只在 SIQ daemon。
8. 已批准的 hold 重试必须重新核验同一上下文链及精确调用，不用 v1 的单 MatchedGrantID 重试逻辑冒充双重授权支持。无法确认执行效果时保留 uncertain，不自动再执行。

## 分阶段实施与验收

| 阶段 | 输出与门禁 |
| --- | --- |
| A | v2 签名文档、严格字段与身份约束、跨语言样例；仅结构与签名，不接入执行。 |
| B | 持久上下文、祖先和调用绑定、撤销/重启/容量与并发；管理凭据不能下放沙箱或模型。 |
| C | 引擎精确双 Grant/祖先交集、受管会话必需上下文、hold/观察回路和兼容性；旧 v1 负向测试保持。 |
| D | 固定业务镜像的 Hermes 可信加载和 final-tool hooks、宿主产品接入；不再依赖测评选择器或轮询器。 |
| E | 日常前端/API、两个真实安装 Skill、切换/并发/撤权/漂移、实际文件/网络效果；完整候选清单和同候选回归。 |

业务仓库当前有大量既有未提交改动。修改前逐文件记录来源和工作树摘要；新增改动单独审查、验证和提交，不吸收他人改动。兄弟仓库之间只使用版本化协议，不导入 SIQ 内部实现或查询其数据库。

## 威胁边界

本设计不把同 UID 可替换的插件自校验当作独立信任根；真实业务依赖受控宿主、隔离的管理凭据及固定镜像/只读安装。若这些条件缺失，必须保持未知或拒绝，不能继承 DGX Spark 的受管证据到普通桌面。单一签名加载文档不能证明多技能隔离已经成立。

## B1：持久上下文的实现约束

v2 记录位于状态目录 `skill-contexts-v2`，撤销位于 `skill-context-revocations-v2`；两者不混入 v1 目录。上下文 ID 为 `sec-` 加 SHA-256 前 16 字节的小写 hex，输入是 `canon.Marshal({"domain":"skill-execution-context/v2","subject":<完整 subject>,"load_id":<原生 load ID>})`；同一次加载不能重签成不同安装、父链或授权。完全相同的重复签发只返回仍通过实时校验的原文，不延长租约。撤销文档采用 v2 schema，绑定原上下文签名，重复撤销只读原墓碑。

签发前必须供应完整可信依赖：验证过的运行身份读取器、签名 Grant 读取器、安装记录及当前安装内容校验、精确 session 绑定、可信原生加载（含精确父链）与任务生命周期读取器、失败关闭的审计写入器。组件不提供“默认通过”依赖。Agent baseline 必须无 Skill 且 deployed/effective；Skill Grant 可按既有安装协议使用已批准的 import Grant，但必须通过安装内容校验。签名、归属、摘要、存活期和任务/加载事实每次重读。

父链最多八层（含当前节点），每层 subject 与 Agent authority 必须相同，引用签名精确一致；叶节点期限不得超过任何祖先、session 或加载任务的期限。父上下文撤销/漂移使后代失效。返回完整权限链给后续引擎计算交集，存储组件自身不做 allow 判断。

每个上下文目录最多 4096 个已发布记录，不淘汰历史来绕过容量；点查及父链读取有界。未知、损坏、重复字段、非规范字段名、额外 JSON 文档、超限或符号链接记录拒绝。签发/撤销先写审计授权尝试，再排他发布签名文件；审计不能替代最终发布事实。沿用 daemon 状态单写者锁，进程内互斥只协调本进程；不宣称跨进程管理可以无锁操作。

B1 不新增公开签发端点、不接入 Engine；后续调用绑定与受管会话必需上下文门禁未完成前不得启用 v2 执行。

## B2：精确调用记录与受管会话

新增 `native-skill-managed-session/v1` 与 `native-skill-call/v1`，分别位于 `native-skill-sessions`、`native-skill-calls`。会话由可信宿主登记实际运行制品及原 Agent baseline；会话记录本身不能批准业务权限。调用绑定必须引用该记录精确签名及原 baseline，携带完整 subject（原生 task 必填）、工具名、原生调用 ID、`trustedcontext.RequestBinding` 格式的参数摘要；不保存参数原文，摘要前拒绝非 JSON/循环参数及超过 1 MiB 的 JSON 参数（HTTP 入口另有限额）。宿主回调每次验证会话/任务/原生调用事实，不能根据请求自报判断无 Skill 或父链。

会话 ID 是 `nsess-` 加 `canon.Marshal({"domain":"native-skill-managed-session/v1","subject":<无 task 的 subject>})` SHA-256 前 16 字节 hex。调用 ID 是 `ncall-` 加 `canon.Marshal({"domain":"native-skill-call/v1","subject":<完整 subject>,"tool_call_id":<原生调用 ID>})` SHA-256 前 16 字节 hex；ID 不含工具名或参数，使相同原生调用 ID 的重写不能生成第二条不同授权。有 Skill 时所有上下文祖先的运行制品摘要还必须与登记会话一致。调用记录要么带精确 v2 上下文引用，要么明确 `no_skill=true`；两者互斥，未知状态不得选择无 Skill。

会话最长 24 小时，调用最长五分钟，签发按 baseline session、宿主生命周期及上下文期限收紧；幂等返回原始有效文档，不续期。会话最多 1024 条、调用最多 16384 条，暂存残留计入目录读取预算，不自动删除历史。记录只追加，审计缺失不发布。绑定的存在不是执行预留，不提供 exactly-once 语义；后续引擎仍必须应用原 hold reservation/observation。

组件 `VerifyCall` 对缺失会话、缺失调用、过期、依赖不可读、上下文撤销和参数漂移一律报错，不提供“找不到就普通 Agent 授权”的返回值。C 阶段需将调用级受管模式绑定到可信 enrollment/运行身份策略，并在决策前选择此必需验证路径；不得仅根据本次请求 claim 或调用记录是否存在决定是否启用保护。此门禁和真实宿主回调接入之前，B2 不作为在线授权入口。
