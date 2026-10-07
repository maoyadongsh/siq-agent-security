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

## C1：决策交集与版本化回执组件

引擎新增可信宿主 `NativeCalls` 查询接口，由该接口基于受管 enrollment/宿主配置返回“必需”状态与完整已验证调用。该状态不能来自模型参数，查询错误或必需但无结果必须 hard deny（包括 warn/audit_only）。未启用的既有 v1 会话保持原路径。原 Intent 必须选择精确 Agent baseline；不能用 Skill Grant 覆盖 Intent 所选 Grant。所有 Skill 祖先逐一按自己的归属执行资源/工具策略，任一 deny 优先，之后 hold，最后才 allow；不得查询“最新 baseline”替代绑定。

新增 `runtime-receipt/v3`，在独立 `receipt.v3.schema.json` 记录 `native_invocation`：精确调用/会话引用与签名、参数绑定、Agent authority 及完整叶到根上下文授权引用。Skill 归属等级采用 `controlled_invocation`。原 v1/v2 合同及签名字节保持；不能以 v1 的 controlled_task 标签隐瞒新的执行语义。无 Skill 的记录保留原 baseline 与明确无 Skill 证明，不制造 Skill 归属。

原生调用的最终参数已由宿主固定；引擎不得在绑定之后静默脱敏改写参数并把旧证据带到新调用。需要脱敏时由宿主生成新的原生调用 ID/绑定，再进行决策。C1 仅新增引擎组件与回执合同，未接入在线启动路径。审批重试在 C2 完成原调用和重试调用的双重活体核验之前明确拒绝；状态 reader/writer 兼容、受管 enrollment 必需门禁和真实宿主 wiring 未验收前不得产品启用。

## C2a：原生调用审批重试

C1 的临时拒绝只在本批完整重试验证通过后解除。审批仍是人工意见，不是执行许可：批准时固定原 Intent 和精确 Agent baseline；读取批准状态及预留前重新核验原调用完整签名证据与全部权限链。模型不能通过改 MatchedGrantID 或使用“最新 baseline”继承审批。

原生重试必须先由可信宿主绑定一个不同的最终工具调用 ID。预留同时核验原调用与重试调用：subject、工具、参数和原任务一致，session 登记签名、Agent authority、明确无 Skill 状态及全部上下文签名/Grant 摘要相同。预留回执记录重试调用自身的 v3 证据与参数绑定，并通过现有唯一 hold_reservation 持久提交。执行前再次重验原调用与该重试记录；缺失、过期、模式降级或链漂移即拒绝。原生最终检查仅允许刚发布 reservation 的本进程成功一次，用内存所有权/已检查位限定；重启恢复只恢复签名事实，不恢复这两个执行许可位。

预留后的状态读取、进程重启、撤权或超时都不能重新授予一次执行；没有观察记录仍为 uncertain。观察继承实际 reservation 的证据，记录已发生的效果，不因执行后权限失效抹掉事实。用户确认未发生时沿原 reconciliation 追加结案，不恢复旧执行许可。此批不改变 v1 审批合同，也不启用 serve；状态及消费者兼容、可信宿主接入仍为独立门禁。

## D1：身份固定的原生调用必需策略

现有 runtime identity v3 已用于请求级身份。新增 v4 作为 Hermes 原生必需策略的根身份、v5 作为继承该策略的请求级身份；原 v1/v2/v3 不增加可选字段。`native_skill_policy` 必须同时包含 `mode=required` 和管理员固定的运行制品 SHA-256。该字段进入身份签名和已有父身份摘要，不能由模型或工具参数选择；发起创建的 v3 请求只适用于管理端。策略声明本身不证明宿主实际加载，实际制品必须在后续可信宿主回调逐次核对。

创建仅接受 Hermes、无 Windows 文件系统 profile、无 Skill 的原 Agent baseline。派生请求身份继承原策略的独立副本，并逐次检查父签名、撤销、固定 Grant、请求租约和完整策略一致性；不能派生较弱模式。已有 root replacement 必须先撤销旧身份；不修改旧签名记录。

原生必需模式查询依据同实例的有效签名根身份，独立于 session/call/SEC 是否存在。已属于 hri 命名空间却没有可验证根身份、存在冲突或身份/Grant 无法读取时返回错误，不返回 legacy。非受管 Agent 及明确旧式有效根身份保留既有路径。具体请求仍须通过 credential 与 session 绑定验证；模式查询本身不授予访问权。管理 API、宿主凭据与在线 Engine wiring 完成前，不开放新创建请求，不能把身份组件测试表述为日常业务验收。

D1 实现的 `RequiredLookup` 先读身份固定策略，再核对原生调用及会话制品摘要；错误保持必需 Authority hard deny。尚未配置该查询的 HTTP 服务遇到新身份返回 503，不进入旧授权路径。候选 reader/writer 低于 5 的回退预检增加有界身份格式检查，即使尚无原生会话，也拒绝 v4/v5 或无法确认兼容的身份状态。此预检不代替签名认证，不改写历史 marker 或发行清单。组件验证见 [D1 验证记录](../development/optimization-opt08-enrollment-validation-20261007.md)。

## D2a：管理与运行端读回

携带原生策略的身份摘要必须明确返回该策略，不能套用旧响应合同后丢失必需模式。新增 identity-issued/v3、request-identity-issued/v2、identity-self/v2、session-enrolled/v3，以及同时容纳原有 POSIX、Windows 与原生身份的 identities/v3 列表。列表 v3 至少包含一条原生身份，版本选择不受条目排序影响。原有响应版本和无策略字段的字节语义保持。

所有原生响应只投影已签名身份中的策略，保留 `runtime_state=unverified`；会话登记成功不是原生宿主验证成功，不据此显示已保护。身份摘要、self、会话响应不包含 token、credential hash 或签名，发行响应沿原协议仅返回本机凭据文件路径。新管理创建入口仍关闭，旧适配器收到新版会话响应必须拒绝，不能因服务端返回 200 跳过原生管控。

前端读取混合列表时验证必需模式、制品摘要、平台与 POSIX 路径解释；旧版本夹带策略或字段冲突均报错，不将其当作普通身份。既有创建流程不能接收含原生策略的旧版发行响应。本阶段只补齐读回和兼容保护，不启用可信宿主传输或原生执行。

## D2b：Linux 宿主元数据通道

DGX Spark 接入采用固定宿主进程的 Unix `SOCK_SEQPACKET` 元数据通道，不向模型或工具下发管理密钥。可信启动器在进程启动后固定宿主可见 PID/UID，并保持 pidfd；进程退出即失效，不按数字 PID 自动重连或转移到新进程。注册 PID 不能来自工具请求，制品、启动归属和只读代码/安装必须由后续启动器独立核验。本组件只提供传输，不替代这些事实核验。

逐包启用 `SO_PASSCRED` 并检查内核 `SCM_CREDENTIALS` 的实际发送 PID/UID；不能只依赖 `SO_PEERCRED`，因为继承连接的子进程可保留原连接建立者信息。丢失凭据、其他 PID、退出进程、附带文件描述符、截断消息和未知字段均拒绝；收到的额外描述符立即关闭。客户端 socket 不可继承，另外每次检查调用进程；内核逐包校验仍负责阻止直接使用继承 socket 的工具子进程。

只在可信启动器指定的本用户私密目录创建精确 socket，不覆盖已有对象；只清理由本次创建且 inode 一致的 socket。该目录将来可作为单独受控挂载暴露，不能暴露整个 SIQ 状态目录。管理凭据和签名私钥始终留在宿主。通道不承载任意执行能力，不产生 Grant，也不承担模型行为判定。

使用独立 `native-host-event/v1` 和 `native-host-response/v1` 帧：严格 JSON、单包最多 64 KiB、顶层事件/结果最多 32 个字段、正向递增整数 sequence。具体事件仍需后续版本化业务合同校验；最终调用只需传递精确绑定摘要，不以此通道传输大参数原文。重复/乱序拒绝，进入处理器前消耗 sequence；响应丢失或格式失败后客户端停止，不自动重试。I/O 有界等待，处理器自身还须另行落实超时。

本组件仅支持 Linux；标准库 `os.pidfd_open` 不可用时，可通过 Python 标准库 ctypes 调用当前进程 libc 的同名函数。没有 pidfd 或消息凭据能力时拒绝，不退回普通 PID 查询。该限定例外不增加宿主传感器、系统调用拦截或新 OS 沙箱，也不证明 macOS/Windows 原生管控。拥有 root/capabilities、可替换可信代码或注入宿主进程的攻击者不在此通道保证范围。

### D2c2：原生函数接入

按 [固定 Hermes 原生分发接入 v1](../../packages/contracts/native-hermes-dispatch.v1.md)，对固定业务镜像生成可核验补丁：覆盖原生任务边界、普通/插件 Skill 文件读取、缓存校验及真正 registry handler 前的不可选门禁。补丁只在新的受控制品中使用，不改用户日常工作树或旧插件默认行为。可信回调尚未连接到在线 Authority 时，默认拒绝，不以测试回调声明产品启用。子任务暂缺精确父任务元数据时明确拒绝；不得以相同 session 或推测上下文降级为 root。

## D2c1：实际 Skill 文件快照

原生加载接入先提供有界的文件快照组件。`native-skill-source/v1` 只记录实际主文件和所读文件的路径摘要、原始字节摘要/长度，以及解码后文本摘要；不包含文件正文、明文路径、Grant、allow 或无 Skill 声明。主文件必须是绝对规范路径的 `SKILL.md`，支持文件必须位于同一目录树。宿主仍须把路径摘要映射到已批准安装，核验完整包和运行制品；一个文件摘要不能替代安装包摘要。

逐级以目录描述符及 NOFOLLOW 打开路径，拒绝任一级符号链接、非普通文件、多硬链接和超限内容；所有描述符不可继承。单文件最多 1 MiB，路径最多 4096 UTF-8 字节/128 组件。读取前后及观察回调返回后核验描述符与路径归属、大小、mtime/ctime。输出文字严格来自被摘要的同一份内存字节，按固定镜像 `read_text(encoding="utf-8-sig", errors="replace")` 的 BOM、替代字符及通用换行语义解码。组件不执行模板、内联 shell 或 Skill 脚本；后续接入不得重新以未核验文件替换返回文本。

每个 reader 仅供一个可信任务使用，最多记录 256 个源路径；首次读固定该路径及主文件内容，后续同任务变更拒绝。缓存命中也重新读取、摘要并调用必需观察回调，不接受仅凭 mtime/size 的缓存；未见过的缓存引用拒绝。回调失败、文件漂移、容量耗尽或 fork 后使用使该 reader 停止，不能自动重置为无 Skill。关闭后不能复用；清空 Hermes 的文本压缩缓存不清除这份任务来源记录。

观察回调只消费元数据，其正常返回不授予执行权限。任务来源、父链、最终调用参数和授权仍由后续应用事件/可信桥接与既有引擎负责。本批不修改现有 Hermes 插件安装、原生读取路径、预处理器或 serve；因此不能将组件通过表述为原生钩子已接入。文件竞态检查是防错补充，不能替代受保护的只读安装和代码挂载。

### D2e：真实安装来源与现有归属链接

按 [native-install-source/v1](../../packages/contracts/native-install-source.v1.md)，来源解析使用当前签名安装、运行绑定及真实字节。现有 Hermes 安装是目标与私密事务文件的硬链接对；D2c1 的默认单链接规则保留，可信 bootstrap 可显式使用受管链接对模式，由必需来源观察验证安装归属和只读挂载后才返回文字。额外第三条链接仍拒绝；该开关不得来自模型或工具参数。组件验证不自动开启新身份或在线产品入口。

### D2f：实际运行进程与受保护挂载

按 [native-runtime-guard/v1](../../packages/contracts/native-runtime-guard.v1.md)，宿主读取其可信启动进程的 Linux `/proc` 只读事实并保持 pidfd；核验真实挂载只读性、代码文件与命名空间，不把容器 API 声明作为唯一证据。仅允许标准库 Python 打开 `/proc`、文件与目录描述符，不增加系统调用监控、提权或新 OS 沙箱。启动后端仍须独立证明镜像、启动归属及底层代码/库保护；普通 Docker 离线试验不是 OpenShell 验收。

### D2g：显式在线宿主接线

按 [native-host-online/v1](../../packages/contracts/native-host-online.v1.md)，daemon 通过显式启动开关加载私有连接配置。独立宿主凭据只发布元数据，普通运行时凭据只提交参数；每次必要 Authority 验证经固定私有 Unix socket 回查实际运行，不从客户端选择回查目标或复用先前成功。Engine 的查询器在构造时固定，server 在监听前一次绑定实际 Store；来源解析使用 D2e，运行事实来自 D2f 及实际启动后端。此接线仍不自动开放新身份创建或宣称 OpenShell/业务验收。

### D2h：适配实际 OpenShell 镜像与进程命名空间

实际 OpenShell 0.0.83 探针确认根文件系统可写，而 Hermes 代码/解释器为 root 拥有且非 root 进程无法写入；进程实际具有 NoNewPrivs 和零 effective/permitted/ambient capabilities。按 [native-runtime-image-profile/v1](../../packages/contracts/native-runtime-image-profile.v1.md) 显式支持受保护镜像文件核验，保留旧挂载 profile。宿主通道可在本次拥有的容器临时目录通过受核验 root/directory fd 建立，客户端额外核对响应的跨 PID namespace SCM_CREDENTIALS；无需放宽现有业务挂载合同。限定写入本次沙箱私有临时通道目录及本实例 socket，不修改宿主业务文件或其他容器，不引入提权、mount 操作或内核监控。
