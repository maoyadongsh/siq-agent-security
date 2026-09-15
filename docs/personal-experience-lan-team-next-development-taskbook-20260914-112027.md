# 个人体验与局域网团队管理后续开发任务书 v4.1

生成时间：2026-09-14 11:20:27（Asia/Shanghai）。适用仓库：`maoyadongsh/siq-agent-security`。

**执行基线：main `4464dfbc8e66c8ec1fb2590b286351595fcd9667`，已包含 [PR #45](https://github.com/maoyadongsh/siq-agent-security/pull/45) 的独立验收修复。** 本书取代 v3 的后续执行顺序；原需求及历史证据不删除。目标继续为三个系统上的个人智能体与 Skill 安全管理，然后局域网团队多设备管理。

## 1. 给执行者的结论

本项目已有可复用的 Go 本地服务、个人 Web/embed、安装/更新事务、权限及回执、平台适配与企业控制面。请在这些模块上增量开发，不另造应用或把产品变成任务聊天工作台。

GLM 上个工作树的成果已选择性验收合入：来源调度、HTTP/Web、诊断及界面异步增量。**N05 可信 Skill 归属和 N06 审批重试的旧实现没有被接受。** 必须先补可信链设计及负向测试；不要把旧文件搬回来恢复其“通过”状态。N02 生产 Git 仍关闭，N09 仍 partial，团队阶段未开始。

2026-09-15 接续顺序以第 15 节为准：继承第 5.4/6.4 节 R01/R02 已验证成果，先执行 OpenShell 现有适配器加固和性能基线，再补 Linux 产品旅程；可独立完成的 R03/R04/R05 不必等待 Windows/macOS。真实平台能力不足时，完成对应安全拒绝与诊断，并将真实正向列 blocked；不得制造通过材料。R 编号是本书执行批次，N/T/UX/LAN 为不变的产品目标映射。

## 2. 已确认的产品决策

1. OS：Windows、macOS、Linux；宿主：OpenClaw、Hermes、WorkBuddy。九个组合均保留，CPU、系统版本、原生/WSL2 分开登记；交叉构建不代表实机支持。
2. 核心价值：发现已有智能体和 Skill，检查并确认权限后启用保护；安全安装新 Skill，运行在用户可控权限内并可追溯。不自动接管扫描到的实例。
3. 原生接入优先；必要时受控启动，用户继续使用原平台界面。界面必须区分发现、组件安装、配置就绪、运行时接入以及实际限制能力。
4. 额外权限由 SIQ 统一确认，系统通知引导打开；一次授权不是长期放权。通知、网页和模型文本均不能自行授予权限。
5. 自动检查版本与展示变化，用户确认后更新；链接、下载及本地目录均在目标范围。可拦截的原平台安装入口按实际能力接入，不承诺全平台拦截。
6. 默认本机保存操作、授权、脱敏参数与结果证据；原文按需明确开启。秘密、完整私人 URL、认证头与原始输出不能进日志/上报/前端持久化。
7. 个人阶段完整验收后再做团队多设备。不能通过重命名或缩小矩阵让团队前置门槛自动通过。

## 3. 当前事实与不可回退成果

| 目标 | 当前真实状态 | 本书继续内容 |
| --- | --- | --- |
| N00 | 已完成旧分支基线核查 | 只检查新出现差异，不重新导入全部旧树 |
| N01 | 状态兼容、迁移/恢复和 Linux 最低门槛已验 | 新状态复用 stateformat/statefs/signing；其他 OS 实机继续 |
| N02 | 受控 GitHub HTTPS 组件已验；生产函数显式拒绝 | 真实网络正负向证据后单独评审启用 |
| N03 | 来源签名存储、调度器、daemon、HTTP、Web、一键停用及 Linux/Hermes 原生更新旅程已验 | 补生产公网来源与其他平台/OS 原生旅程 |
| N04 | 安装入口提示、分层诊断、loopback 探测增量已验 | 九组合能力、实际版本与原平台入口核验 |
| N05 | R01 安全组件、服务级活体、Linux/Hermes 任务级及 Linux/OpenClaw 会话级原生调用已验；其他系统仍 partial | 在 R05/R07 扩展平台矩阵并保持两种证据等级边界 |
| N06 | R02 可信预留、人工结案、Linux/Hermes/OpenClaw 原生恢复及 Linux 通知总线传输已验，平台矩阵仍 partial | 补 WorkBuddy 原生能力、Linux 视觉确认及 Windows/macOS 通知证据；OpenClaw 原版宿主继续安全拒绝 hold |
| N07 | Linux 和 Windows 有已合入的增量 | Windows sunbo 持续开发，macOS Luke 负责；生命周期整体验收未完成 |
| N08 | 异步清理、93 项前端单测、30 项会话/发现及 7 项更新浏览器检查已验 | 串联跨平台完整用户旅程；组件替身不充当原生 |
| N09 | v2 校验已加严；同一当前候选的 6 条 Linux 腿已逐行登记，仍无 complete_acceptance | 补产品安装/卸载、真网、WorkBuddy、Windows/macOS 与其余 J 行 |
| T01–T06 | 未开始 | R07 关闭个人门槛后按第 11 节执行 |

必须保留 PR #38 的实例目录身份/权限保护、PR #40 的 Windows 增量、PR #41 的 N09 逐行证据约束及 PR #45 的安全修复。新出现 Windows/macOS PR 应独立核验，不根据标题或 CI 数量宣布系统完成。

### 3.1 事实源与阅读顺序

- 本书、[最新台账](personal-experience-closure-progress-20260913.md)、[本次复核报告](evidence/personal-experience/glm-stage-review-20260914/report.md)。
- 仓库与对应模块 `AGENTS.md`；ADR-011、`agentshield-design-v1.md`、`agentshield-dev-spec-v1.md` 及 `packages/contracts/`。
- [N03 来源调度规格](personal-experience-n03-update-source-spec.md)、[ADR-0051](adr/0051-controlled-hosted-git-source.md)。
- [N09 独立复核](evidence/personal-experience/n09-independent-review-20260914/report.md)、`scripts/personal-experience/n09-baseline-check.py`、`n09_evidence.py` 及对应测试。
- [共享协作规则](personal-platform-collaboration-acceptance-20260913-202355.md)、[Windows 任务书](personal-windows-sunbo-taskbook-20260913-202355.md)、[macOS 任务书](personal-macos-luke-taskbook-20260913-202355.md)。

规格先更新，新增/变更机器协议必须有版本化 schema，再同步实现和双端样例。有效权限只能来自后端；准入 declared、推断 inferred、回执 observed 不得互相提升为有效授权。

## 4. 工作树、旧成果与协作

### 4.1 新执行者从最新 main 新建分支；接续者保留当前工作树

当前维护者接续位置是 `kimi/personal-v4-r01-20260914`，工作树名 `siq-personal-v4-r01-20260914`，起点 HEAD `b303c6f92392f3a44c306d81ad7323c6291ef4f2`。本书更新和大量 R01–R07 成果尚在该树，不能假定已在远端 main；接续者先核对差异和本地证据，不能另开空树丢失成果。其他设备仅从已合并版本接续，不要求复现维护者绝对路径。下面命令只适用于新执行者，不是对当前脏工作树的切换指令。

在自己的克隆中执行，下面命令不会切换或覆盖原 GLM 工作树；路径可以根据设备调整：

```bash
git fetch origin
git merge-base --is-ancestor 4464dfbc8e66c8ec1fb2590b286351595fcd9667 origin/main
# 上一步失败：先调查仓库/引用，不在错误基线上开工。
git worktree add -b glm/personal-v4-r01-YYYYMMDD ../siq-personal-v4-r01 origin/main
```

进入新目录后先记录 `git status --short`、`git rev-parse HEAD`、运行环境。分支名日期自行替换且避免与已有分支重名。不要执行 `git reset --hard` 或清理别人的工作目录。

### 4.2 旧 GLM 成果处置

旧分支 `glm/personal-next-20260913-193405`，原工作树通常位于 `/home/maoyd/siq/worktrees/siq-personal-next-20260913-193405`。此本机路径只用于找到历史来源，协作者无需有同一路径。

[262 路径来源清单](evidence/personal-experience/glm-stage-review-20260914/source-inventory.json) 固定当时 HEAD 和每个原始文件摘要。它证明来源范围，不证明原文件已通过。`review_candidate` 已经选择性修复整合，`already_in_main` 采用主线新版，`held` 保留在旧树。

特别禁止整体覆盖 `internal/state`、`internal/receipt`，禁止整包搬入旧 N05/N06 原生 runner、旧 matrix 和“已完成”台账。可以选取测试素材，但必须先解释测试真正证明什么，且新候选必须重新运行。旧记忆中的完成声明优先级低于 main、任务书及证据。

### 4.3 协作者所有权

| 执行者 | 主要范围 | 交接要求 |
| --- | --- | --- |
| GLM | Linux、共享核心、协议、Web 与证据工具 | 公共 API 变化先落规格和迁移说明；不替协作者宣称实机通过 |
| sunbo | Windows 实测、问题定位及系统适配修复 | 系统/CPU/原生或 WSL2、NTFS/ACL、Task Scheduler 与三个宿主分别取证；当前仍在开发 |
| Luke-zzZ-0 | macOS 实测、定位及适配修复 | macOS/CPU、权限、LaunchAgent 与三个宿主分别取证；设备配置尚需其确认 |

各人从最新 main 新建小批次 PR，避免同时改共享核心同一文件；必要公共更改先形成可审阅协议方案，由维护者协调。不要直接推 main、强推别人分支、批量关闭 PR、修改保护规则或替他人发消息。

## 5. R01：可信 Skill 执行上下文（N05，最高优先级）

### 5.1 需要解决的问题

旧 `internal/state/skill_attribution.go` 忽略 sessionID，把调用方 skill claim、安装内容摘要与 RuntimeGrantWithSeq 查证组合成 verified。它只能证明安装及授权存在，不能证明“这一工具调用由这个 Skill 引起”。只在 engine 再比一次 grantID 仍不能弥补来源不可信。

### 5.2 实施顺序

1. 编写 N05 信任边界规格：列出用户文本、模型文本、skill claim、适配器请求、受控宿主上下文、SIQ 状态各由谁产生；说明每项可否被模型或其他 Skill 复制。
2. 核实当前 OpenClaw/Hermes 版本在实际工具调用边界能给出哪些不可由模型自行赋值的上下文；平台不提供时，选现有受控启动路径上的可执行最小方案。不能声称安装钩子就等于可信宿主。
3. 定义并实现同调用绑定。至少关联：平台实例、验证主体、会话/任务、工具调用 ID、工具及最终参数摘要、安装身份和内容修订、Grant/Authority 修订；根据威胁模型定义签发方、验证方、有效期和失效条件。字段格式本身不是信任。
4. 将可信上下文与工具最终执行点绑定。重写参数后必须重验，不能先对安全参数签名后执行另一组参数；跨 Skill/会话复制上下文应失败。禁止让适配器持有 SIQ 状态签名私钥。
5. 无可靠来源时保持 unknown/inferred，明确说明能力缺口。Agent 权限与 Skill 权限的交集必须由后端算出；不允许凭伪造归属借用另一个 Skill 的权限，也不允许去掉 claim 绕过已知不可信 Skill 限制。
6. UI/回执展示证据等级和关联来源，只对已经证明的范围显示可信；安装状态不直接显示运行保护。

### 5.3 必须通过的验收

| 场景 | 预期 |
| --- | --- |
| 真实受控调用、正确上下文与有效授权 | 同一实际调用、授权和脱敏回执关联一致 |
| 任意请求复制合法安装摘要、grantID 或 skill claim | 不能产生 verified 或获得 Skill 专属放行 |
| 同一 Agent 下两个 Skill；一个权限更宽 | 较窄 Skill 不能借用另一 Skill 权限 |
| 同 Skill 跨实例/会话/任务/调用复制 | 拒绝并且无工具副作用 |
| 参数在许可后改变；同名 Skill 内容替换 | 旧上下文失效，必要时重新审批 |
| Grant 撤销/修订、安装移除、服务重启 | 旧上下文不能恢复已失效权限 |
| 缺来源或平台不支持 | unknown/明确不可用；不得默认可信 |

交付：规格/合同、实现、正负向与并发测试、至少一个真实可执行平台的调用证据。缺原生条件时可以完成安全组件批次，但 R01 原生门槛保持未完成。证明仅抵御模型可控输入时必须说明该威胁范围，不能扩展宣称抵御已被攻陷的宿主或 OS 沙箱隔离。

### 5.4 2026-09-14 接续落盘状态

R01 已完成可信边界规格、`skill-execution-context/v1` 与撤销合同、Go 签发/验证/权限交集、Hermes task ID 透传、回执/Web 证据等级和本地服务级活体脚本。接续复核修复了四类阻断/安全问题：离线 CLI 缺真实 Hermes target resolver；CLI 未取得状态单写者锁；每次验证未重读 runtime identity/session binding；无 SEC 的安装 Grant 在旧开关关闭时仍可凭复制 claim 放行。另补齐 receipt `call_binding` 合同、会话有效期钳制、会话/任务 SEC 重叠冲突、身份替换扫描和证据秘密清理。

[R01 本地服务级证据](evidence/personal-experience/r01-skill-context-20260914/report.md) 使用隔离 HOME/HERMES_HOME/state、真实候选二进制和真实 HTTP/签名状态完成 57 步：正确上下文 verified；无 SEC、跨会话、跨任务、claim 切换、SEC 撤销、Grant 撤销及安装内容替换均不能获得放行；离线 CLI 在 daemon 锁下零写入；回执链和证据 SHA256 通过。该报告明确是“本地服务级等价适配器 HTTP 重放”，未启动模型、未在 Hermes 宿主插件进程中执行真实工具，因此 N05/R01 状态为 **partial（安全组件与服务活体通过，原生门槛待补）**。同 Agent 两个真实 Skill 的宿主级交叉用例也仍待原生批次。

修复 R02 过期边界与 Hermes 清单声明并重建最终本地候选后，[R01 最终候选回归](evidence/personal-experience/r01-skill-context-final-20260914-2110/report.md)以同一 SHA256 `f4b5c23c…7420c` 再次通过 57/57，完整清单复核通过。证据类型仍是本地服务级 HTTP 重放，不提升原生门槛状态。

[R01 接续实现独立复核](evidence/personal-experience/r01-skill-context-review-20260914.md) 记录本轮阻断原因、安全修复、全仓测试、竞态检查、证据脱敏与四平台交叉构建摘要。该记录只证明当前未提交工作树的阶段性质量，不代表已提交、已合并、已发布或对应系统实机通过。

2026-09-14 晚间原生验收发现 Runtime Identity 的服务端 Intent 任务与 Hermes 每轮宿主任务被错误复用为同一个 `task_id`，导致原生调用在取得 verified SEC 后仍以 `intent_task_mismatch` 拒绝。接续实现以追加字段 `runtime_task_id` 拆分两种身份：可信 Intent 仍严格绑定 `task_id`；SEC、同调用摘要及审批重试绑定宿主任务；两者均进入签名回执。普通 Intent 的错误任务提示仍拒绝，不能借新字段绕过。

[R01 Linux/Hermes 原生 SEC 验收](evidence/personal-experience/r01-sec-hermes-native-20260914/report.json) 使用公开 `hermes chat --oneshot` 入口、真实插件钩子与文件工具、隔离 HOME/HERMES_HOME、真实候选二进制和本地确定性模型完成 11 项检查：同 Agent 安装窄/宽两个 Skill，宽 Skill 不能借用目标身份；任务级 SEC 的真实读取执行，写入在副作用前拒绝；allow/deny 回执均为 `controlled_task` verified 且 `call_binding` 可复算；新 Hermes 任务不能复制旧 SEC；链验签、测试观察器移除和产品配置恢复均通过。模型端点仅为本机确定性 fixture，未调用付费或外部模型；测试观察器只上报宿主生成的 session/task，不持有 SIQ 凭据或授权。由此 **R01 要求的“至少一个真实可执行平台”原生门槛已完成**；OpenClaw 的会话级能力和 Windows/macOS 实机覆盖仍归 R05/R07，不能由本证据代替。

R04-E 复核时进一步收紧该 runner：Hermes 现在通过公开 `--skills` 参数明确预载目标 Skill，名称只在宿主生成的 system/developer/tool 材料中检查，用户提示词不能满足加载断言。收紧后的 R01 仍为 11/11，通过结果和 SHA256 已更新到原证据目录。

[R01 Linux/OpenClaw 会话级 SEC 验收](evidence/personal-experience/r01-sec-openclaw-native-20260914/report.json) 使用公开 `openclaw agent --local`、真实 SIQ 插件钩子和文件工具完成 10 项检查。验收首先暴露并修复了两个产品阻断：Skill 权限/安装目标只支持 Hermes，以及安装器的硬链接发布被 OpenClaw 2026.5.12 安全读取器拒绝。修复后，OpenClaw 能从产品管理目录发现并加载 Skill；无 SEC 的读取在执行前拒绝，管理员签发绑定已注册原生会话与安装记录的 SEC 后读取成功，撤销后同一会话再次失败关闭，`controlled_session` 调用摘要可复算且回执链通过。OpenClaw 未提供可信的单 Skill 工具因果字段，因此该证据只证明会话受控和 Skill 可用，不能提升为 `controlled_task`，也不代替 Windows/macOS 实机覆盖。

## 6. R02：审批后的可信继续执行（N06）

### 6.1 禁止恢复的旧逻辑

旧 `internal/receipt/action_state.go` 的消费匹配跳过 SessionID，并在 AuthorityRevision 看似 64 位摘要、身份相同时放宽 IntentID/TaskID。相同身份修订不是跨任务审批许可，不能作为兼容捷径。保留主线严格拒绝，先设计显式重试关系。

### 6.2 实现与状态机

1. 说明宿主 hold → 用户确认 → 恢复真实工具调用的路径：是否同调用重试、是否生成新 task/session、宿主能否真正暂停。无法暂停应报告需要用户重试或不支持，不能把另起任务冒充恢复。
2. 设计由可信服务端签发/验证的有限期重试关系，绑定原 hold、主体、实例、原始调用以及批准的最终参数/权限修订。新会话或任务只有经过明确允许的重试关联才能使用；普通新任务绝不复用。
3. 明确待确认、批准、拒绝、超时、撤销、预留消费、完成、失败/不确定等状态及各转移持久化点，复用既有签名/不可变记录和恢复设施。新增文档先写版本合同。
4. 原子消费与真实执行关联；双请求、重启、网络重试不能执行第二次。外部副作用与本地状态不能原子提交时，应暴露不确定/待核对状态并禁止盲目自动重试；不能承诺无法证明的 exactly-once。
5. 审批后再次校验当前 Authority/Grant、工具参数、安装内容与期限。审批不会绕过组织上限、硬拒绝或服务失联条件。
6. SIQ 确认窗口显示准确对象、动作、资源、期限和一次/持续范围；系统通知仅含脱敏提示和安全入口。注销或切换身份不能继续展示或提交旧审批。

### 6.3 验收与交付

必须覆盖拒绝、超时、撤销、重启前后、两次并发消费、不同主体/实例/Skill/任务、篡改参数、失联，以及原生宿主实际恢复。使用隔离临时文件等可观察动作，记录允许一次后真实副作用恰好一次、拒绝时为零；数 allow 回执不算副作用证据。

额外验证恢复窗口的故障注入：批准已持久化但未执行、执行已发生但结果未落盘、结果重复送达。记录选择拒绝、查询或人工恢复的准确行为。桌面通知实机由对应 OS 负责人验证；Linux 通知脚本成功不代替 Windows/macOS 通知。

R01 的可信绑定作为 R02 的共享基础；R02 状态机和严格匹配测试可先推进。不要为跑通演示削弱 R01 或主线判断。

### 6.4 2026-09-14 接续落盘状态

[R02 可信重试组件复核](evidence/personal-experience/r02-trusted-retry-review-20260914.md) 已落盘：新增版本化
预留/状态合同、签名 `hold_reservation`、并发唯一预留、后续读取 uncertain、相同效果的新审批循环拒绝、
reservation 关联 observation、Hermes 精确重试适配和 `local-confirmations/v2` 管理投影。16 路并发测试中
由唯一预留方写入隔离临时文件，真实可观察副作用恰好一次；预留后结果缺失时只允许核对和补交结果。

接续又完成 `hold-execution-reconcile/v1` 管理结案：确认页展示 reservation 绑定并要求用户先核对外部
结果，可签名记录“已发生/未发生”；错引用、错哈希、相反结论和已有 observation 均冲突，重启后保持
completed/cancelled，旧 reservation 永不恢复。已预留状态不会因审批期限经过或随后撤销授权而隐藏
uncertain。

后续独立复核修复了通用 24 小时动作清理遗漏：未结案 reservation 现在跨动作窗口和服务重启保持 uncertain、继续占用受限容量并出现在管理核对列表，相同副作用仍被阻断；管理员可以在过窗后绑定原 reservation ID/hash 结案。不得为恢复容量自动删除可能已经发生的副作用记录。

随后以新增的双任务身份合同消除了 Runtime Identity Intent 任务与 Hermes 宿主任务冲突，并升级原生审批探针。[R02 Linux/Hermes 原生批准重试](evidence/personal-experience/r02-hermes-approved-retry-20260914/report.json) 在同一个公开 `hermes chat --oneshot` 进程中完成：首次真实 `write_file` 被 hold 在副作用前；本机管理 API 按不可变回执批准；同参数、新 tool-call ID 的重试先读取批准并产生唯一 `hold_reservation`，随后真实文件工具写入一次且 observation 绑定 reservation；另一路拒绝后重试保持阻断并无文件。回执链验签通过。模型为本地确定性 fixture，确认操作者为自动测试身份，不代表人工浏览器点击或桌面通知实机。

因此 R02 的 **Linux/Hermes 原生恢复门槛已完成**。随后 [R02-F Linux/OpenClaw 审批后签名预留验收](evidence/personal-experience/r02f-openclaw-approved-retry-20260915/report.md) 修复 OpenClaw 只重查批准、未消费预留的缺口：受信 `beforeExecute` 用最终参数取得唯一签名 reservation，after hook 以独立执行尝试 ID 绑定 observation。真实 gateway、审批管理器和临时补丁宿主 18/18 场景通过；原版宿主缺检查点时仍在平台审批前安全拒绝。测试使用合成工具与自动操作者，未证明真人点击或真实外部系统副作用。

同一候选的 [R02-G Linux 桌面通知传输验收](evidence/personal-experience/r02g-linux-desktop-notify-20260915/report.md) 又以真实 SIQ daemon、`notify-send` 和 GNOME session bus 完成 6 项检查：pending hold 触发的系统 Notify 调用被真实会话服务接受，正文仅含待确认数量，未泄漏工具、参数和回执标识，测试结束后明确拒绝 hold 并验签。远程 TTY 无法观察屏幕像素或证明用户看见通知，因此只记“Linux 通知传输 verified”，不记视觉交互完成。

整体 N06 仍为 partial：WorkBuddy 原生恢复、Linux 视觉确认及 Windows/macOS 桌面通知实机证据未完成；OpenClaw 检查点也尚非上游官方能力。外部副作用与本地预留无法组成跨系统原子事务，预留响应丢失仍必须显示 uncertain 并人工核对，不宣称 exactly-once。

## 7. R03：安全 Git 真网验收及受控启用（N02）

主线 `internal/skillimport/gitsource.go` 已有 `fetchHostedGit` 组件：GitHub 元数据解析 ref 到固定 commit，再获取固定 commit 归档。默认生产 `productionGitFetch` 仍返回 `ErrGitTransportUnavailable`；API 返回 503、Web Git 选择禁用。测试缝仅供包内测试，禁止暴露配置开关。

1. 阅读 ADR-0051 和现有负向测试，复用现有下载限制；不恢复外部 git clone 为生产路径，不新增通用任意 URL 代理。
2. 首先记录实际网络环境。本次 Linux 对 api.github.com 解析到 198.18.0.29，被公网策略正确拒绝。若仍如此，记录 blocked 并继续 R01/R02/R04；不得改 hosts、绕过公网校验或用替身宣布真网通过。
3. 在具备真实 HTTPS 直连环境的执行端，用明确公开、可复现、内容无执行需求的测试仓库检验：有效 ref、40 位固定 commit、子目录、上游前进、固定 commit 不变、不可访问/不存在仓库。记录解析/最终连接边界和元数据/归档关联的脱敏证据。
4. 配合受控 TLS fixture 覆盖重定向、代理、私网/loopback/link-local、DNS 变化、userinfo、恶意 ref、超时/取消、超限归档、路径逃逸、嵌套压缩包及符号链接。真实正向与 fixture 负向分别分类。
5. 证明失败无导入/安装/Grant 状态污染；内容不能执行；工作树、环境和宿主配置不受影响。所有来源摘要仍绑定固定对象。
6. 真实证据达到规格后，用独立小提交接入已验证生产实现，同步错误语义与 Web 可用性，并重跑端点及真实安装/检查流程。不能仅删除 503 门禁而没有证据与回归。

完成定义：受控传输有真网证据、生产调用路径确实使用它、UI 与错误语义一致。仅完成组件/负向时仍标 partial。

### 7.1 2026-09-14 本机复核

[R03 真网前置检查](evidence/personal-experience/r03-hosted-git-network-20260914/report.md) 再次确认
`api.github.com`、`codeload.github.com`、`github.com` 在当前环境分别解析到 `198.18.0.29/.4/.8`。
该范围是非公网基准测试保留地址，受控下载器应拒绝。未绕过地址校验，生产 Git 入口维持关闭；R03/N02
保持 partial，解除条件为具备真实公网解析与直连 TLS 的执行环境。

## 8. R04：原生 Skill 更新与低成本管理（N03/N08）

### 8.1 继承现状

保存公开 ZIP 来源是用户显式动作；无查询串/认证信息的来源才可持久化且绑定原安装定位摘要。默认 24 小时间隔，daemon 每 5 分钟取到期条目、启动不立即取数，失败退避。调度写结果比较取数前签名，不能覆盖关闭/重存后的记录。未知版本或损坏状态即使是关闭操作也不能覆盖。Git 来源受 R03 门禁约束。

现有 Web 来源启停、手动检查、结果校验、取消和身份变化清理均已验。R04-B 已新增独立 `local-skill-update-source-disable/v1` 合同：已保存的 Git/ZIP 来源停用不再要求 URL，只能复用当前有效签名记录；未保存、未来版本、损坏记录、来源变化和绑定漂移全部拒写。组件复核见 [R04-B 报告](evidence/personal-experience/r04b-update-source-disable-20260914/report.md)。

### 8.2 需要交付

1. 隔离原生 profile 完成安装 V1 → 使用 → 发现 V2 → 展示内容与权限差异 → 用户取消保持 V1 → 再比较和确认 → 更新生效 → 回执关联；最后安全移除。分别证明各阶段文件/授权的前后状态。
2. 自动检查仅写独立调度数据，不能安装 V2、提升权限或自动确认。权限差异在检查阶段仍可明确“待更新比较”，不伪造已经完成权限分析。
3. 负向：来源不可达/被改指向、上游返回错误内容、未来状态、内容超过 200 条截断、并发移除/检查/更新、用户改动目标、审批/确认后源改变、崩溃恢复。截断报告必须提示完整变更未列出，不能当作仅有这些改动。
4. **R04-B 已完成组件验收**：针对已经保存的来源，后端只基于当前有效签名记录停用，无需用户重复粘贴；未知/损坏/陈旧状态拒写，重复停用逐字节幂等。前端覆盖停用、未保存、旧版本/错误和迟到结果。该结论不替代第 1 项原生更新旅程。
5. 对无连接显示可执行的启动/重连入口，不以“决策 API 不可达”作为无解释终点。连接成功后正确恢复页面，不能重复扫描创建新身份。保留本地 `/`、`/demo` 与个人页面的本地入口语义。
6. 移动宽度、键盘、取消、重试、注销跨标签页、快速切换不同安装对象有验证；旧对象迟到响应不得改变当前对象状态。

本批 7 个更新面板场景是 API 响应 fixture，不是原生更新。可以复用 runner 扩展，但新报告明确类型，不能将已有截图更名充当真网证据。

### 8.3 2026-09-14 当前候选集成状态

[当前候选集成报告](evidence/personal-experience/r04-update-journey-20260914/report.md)使用新构建二进制、隔离 daemon/Hermes profile 和真实 Chromium 重跑了 7 项更新事务及 28 项会话/发现/断连恢复检查。V1 保留、V2 差异、显式确认、丢响应查询恢复、准备失败中止、旧 Grant 撤销、新 Grant 不自动激活、移动端确认、重新连接和重复扫描身份稳定均通过。该证据没有启动 Hermes/OpenClaw 模型，没有宿主工具调用，也没有真实公网来源，R04/N03/N08 继续为 partial。

修复 R02 过期边界与 Hermes `provides_hooks` 清单警告后，[R04-D 最终本地候选复验](evidence/personal-experience/r04d-final-candidate-20260914/report.md)以 SHA256 `f4b5c23c…7420c` 的重建候选再次通过 R01 57/57、更新 7/7、会话与发现 30/30；真实 Hermes CLI 在隔离 `work` profile 验证原生配置生命周期，Plugin Doctor 无警告。仍未启动模型或执行宿主工具调用，不能关闭 R01/R02/R04 原生门槛。

[R04-E Linux/Hermes 原生更新验收](evidence/personal-experience/r04e-hermes-native-update-20260914/report.md)以当前未提交候选完成 15 项真实宿主检查：V1 明确预载和真实读取、pending 候选比较后取消保持 V1、批准后重新比较与签名计划、明确更新、旧 Grant 撤销与旧身份失效、V2 重新激活/换身份/换 SEC、V2 明确预载和真实读取、内容归属摘要切换、回执链验签及最终安全移除。该批完成 R04 第 1 项的 Linux/Hermes 原生门槛；V2 为明确导入的本地目录，当前网络环境的公网调度取数仍 blocked，其他平台与 OS 不由此代替，因此 N03/N08 整体保持 partial。

### 8.4 2026-09-15 Linux/OpenClaw 更新复核

[GLM 原报告](evidence/personal-experience/r04-openclaw-native-update-20260915-171614/report.md)保留为历史记录，其中 UP07 把 HTTP 201 创建成功误作拒绝，UP03 只改请求签名而未修改候选，不能沿用其全部负例结论。[复核报告](evidence/personal-experience/r06-r04-r07-review-20260915-223037/report.md)以修复候选重新运行真实 OpenClaw 更新链：分别验证错误摘要拒绝、已导入快照不随外部源消失而变化、有效签名下暂存内容被篡改返回 409 且原目标/两侧 Grant 不变，保留取消、重启提交、版本切换、撤权、移除及回执验签。UP07 的未来/损坏/陈旧签名状态仍不能用摘要负例替代；UP05 多操作员并发和 UP10 公网中断仍待补。R04/N03/N08 保持 partial。

## 9. R05/R06：平台能力、生命周期与协作（N04/N07/N08）

R05 先登记本机可用宿主版本、配置根、profile、CLI 路径及运行方式，核对原平台安装、工具调用前后、暂停/恢复和归属能力。每个能力记录“检测到什么、配置了什么、实际阻止了什么、还缺什么”。WorkBuddy Linux 若无上游运行时，明确 blocked，继续可完成模块；不能用目录探测代替桌面运行。

R06 与 sunbo/Luke 并行推进。两人按其任务书在真实 OS 完成下载/校验 → 首次启动 → 浏览器管理 → 后台注册/启动/停止 → 更新/旧状态拒写 → 异常恢复 → 保留数据卸载。必须核实当前用户权限、路径含空格/中文、占用端口、软链接或 reparse point、身份替换、权限/ACL 与未知文件保护。

公共核心修复有针对性负向测试再合入；不要为了一个 OS 删除其他 OS 安全断言。平台特有行为放在既有平台层，保持 Go stdlib 和四目标构建。Linux systemd fixture、Windows Task Scheduler 模拟、macOS LaunchAgent 模拟必须与实机结果分开。

安装与后台服务变更先预览后确认，严格只操作测试实例/当前用户明确对象，不全局清理进程、不广泛 disable、不覆盖未知文件。原系统服务和现有日常 profile 不作为默认测试场地。

交付制品来源、摘要、签名身份、支持矩阵和排错说明。测试签名、交叉构建或一个 OS 的成功不代表正式三系统发行；发布动作单独授权。

### 9.1 2026-09-14 Linux 主机只读盘点

[R05 Linux 宿主能力报告](evidence/personal-experience/r05-linux-host-capabilities-20260914/report.md)固定了当前 Linux/aarch64 主机与版本；[R05-C 最终候选双宿主合同](evidence/personal-experience/r05c-final-host-runtime-contract-20260914/report.md)证明真实 OpenClaw 运行时加载两个 SIQ 工具钩子，真实 Hermes Plugin Doctor 对候选安装资产无警告导入并注册两个钩子，二者卸载均保留所测无关配置。后续 [OpenClaw 管理接入原生验收](evidence/personal-experience/r05d-openclaw-managed-native-20260914/report.json)完成真实工具调用前拒绝、正常读取、原文按需采集、回执链及身份撤销失败关闭；R01 的 Hermes/OpenClaw SEC 报告又分别证明任务级与会话级 Skill 归属门槛。WorkBuddy CLI/配置根不存在，保持 blocked；OpenShell CLI 存在但所选 `nemoclaw` 网关拒绝连接，身份未验证且仅为 L0。R05/N04 仍为 partial，下一步是 Linux/WorkBuddy 上游运行时与 Windows/macOS 实机覆盖，不能用当前两宿主结果代替。

### 9.2 2026-09-15 Linux 生命周期复核

[原生命周期报告](evidence/personal-experience/r06-linux-lifecycle-20260915-161515/report.md)不足以关闭 LC01–LC09：若干安装输出未归档，版本标签不足以证明对应源码/状态兼容，LC04 撤权重启覆盖不完整，LC09 删除状态后再安装不能证明保留状态重入，旧失败日志曾被覆盖。原文件保持原样。

[复核报告](evidence/personal-experience/r06-r04-r07-review-20260915-223037/report.md)新增真实 systemd 用户服务保留状态重入：特殊字符二进制/状态路径、精确实例注册、幂等启动、停止与重启、注销后保留配置和身份、在同一状态重新注册启动、最终产品 teardown 清理；签名密钥仅比较摘要，不输出内容。该证据属于 runtime 用户服务生命周期，不代表正式发行包升级、真实登录/重启整机或 R06 安装实例直接承载 R07。GLM 遗留两个测试单位已核实归属并 teardown，原状态保留。R06/Linux 保持 partial；sunbo/Luke 原任务不变。

## 10. R07：N09 逐行验收及个人阶段关闭

使用已有 `personal-acceptance-baseline/v2`，九格 × J1–J11。J 项范围继承当前 main 的独立复核矩阵，不重新定义编号换取通过。每行 coverage 必须引用该 leg 真正执行过的检查，不能一条 leg 成功就把全部行设 complete_acceptance。

逐行最低核验范围如下；这张表帮助执行，不替代矩阵 schema 和原 UX 的验收要求：

| 行 | 要验证的用户行为 | 不能用来代替的材料 |
| --- | --- | --- |
| J1 | 产品安装、服务启动并进入管理 UI | 仅装适配器插件 |
| J2 | 发现已有 Agent/Skill、非默认目录及实例关系 | 单个固定目录 fixture |
| J3 | 确认后接入对应真实实例，保留用户配置 | 检测到安装文件 |
| J4 | 最终候选的权限允许/拒绝及零越权副作用 | 单条允许读取 |
| J5 | 额外审批、通知、可信恢复和重放/失联处理 | 记录了一条批准或 allow |
| J6 | Skill 安装、确认更新、移除，含已开放生产来源 | 适配器装卸或仅本地替身更新 |
| J7 | 具体 Skill 与实际工具调用的可信因果关联及追溯 | 安装摘要、模型自报或可复制 claim |
| J8 | 服务不可达时需要阻断的调用不执行 | 健康接口返回失败 |
| J9 | 服务/会话重启恢复，旧权限与身份仍受约束 | 同端口重新监听 |
| J10 | 产品与接入生命周期卸载、撤销及用户数据保留 | 只删除一份插件文件 |
| J11 | 默认脱敏、原文显式授权/到期/撤销、导出隔离 | 一张默认关闭的截图 |

1. 新候选固定 main/实现 SHA、二进制 SHA256、OS/CPU、平台版本、profile 类型、起止时间、准确命令及退出码。
2. 原生、受控启动、组件、单测各自分类；没有实机的项写 blocked/unverified 和解除条件。校验器说 valid 只表示结构/引用/摘要有效，不代表产品通过。
3. 旧 `n09a-linux-baseline-*`、`n09b-openclaw-runtime-*` 是旧构建观察。当前独立复核已经撤销从其整体结果推导 J1–J11 complete_acceptance；保留旧原文，不覆盖摘要。
4. 针对同一个候选逐行补齐安装/发现/接入、权限允许与拒绝、额外审批、Skill 安装更新移除、可信归属与追溯、服务失联、恢复/卸载及隐私的真实范围；CPU 与原生/WSL2 信息随证据保留。
5. 关键负向必须断言零副作用或预期可恢复变化；对审批恢复必须真实执行计数。任何权限绕过、凭据泄露或未知文件破坏先修复再复验。
6. Windows/macOS 成果合入后，核查候选一致性；跨候选复用证据须标注来源及差异评估，不能替换原始报告中的 binary_sha256。

### 10.1 2026-09-15 当前候选矩阵

[当前候选逐行矩阵](evidence/personal-experience/n09-current-candidate-20260915/report.md)已将 Linux/Hermes 的 SEC、批准重试、V1→V2 更新和 Linux/OpenClaw 的 SEC、批准重试、桌面通知六条证据腿统一到候选二进制 SHA256 `b6e7650f…6708`。`n09-baseline-check.py` 对 9 格 × 11 行、报告摘要、同候选绑定和逐项 coverage 校验通过；旧 `fe03e7e0…` 矩阵保持历史原文，没有混入当前候选。

该矩阵没有任何 `complete_acceptance` 行。Linux 两宿主只对已实际执行的行为登记 `controlled_start`；OpenClaw 批准恢复仍依赖临时配套检查点与测试执行器，Linux 通知只证明真实 GNOME 会话总线接受。J1 完整产品安装、J6 生产公网来源、完整卸载/隐私旅程、Linux/WorkBuddy、Windows/macOS 及通知视觉确认仍未完成，因此 N09 保持 partial，T01–T06 继续受门禁约束。

交付报告说明所有 N/UX 对应的验收、仍有限制、外部发布事项及支持矩阵。只有原目标要求的组合全部有可复查证据，或用户明确批准变更范围后，才能关闭 N09。不能把 unavailable 当完成。未经此门槛，不执行 T01–T06 产品开发。

### 10.2 2026-09-15 旅程复核及当前候选矩阵

[原 GLM 矩阵](evidence/personal-experience/n09-glm-batch-20260915/report.md)是旧候选历史证据，不承接为修复候选的验证。[复核报告](evidence/personal-experience/r06-r04-r07-review-20260915-223037/report.md)与[新矩阵](evidence/personal-experience/r06-r04-r07-review-20260915-223037/n09/report.md)登记同一新候选的 R04/R07 腿。修复四个页面加载竞态及适配器同值选择卡死，取消页面重试；在同一浏览器文档内重启服务验证 401、UI 失效、历史保留及重新配对；补真实原文任务授权、采集、撤销和未到期密文/回执的逐字节保留检查。

仍未串联“正式安装包→安装实例的 systemd 服务→浏览器旅程”；审批腿是 HTTP/UI 验证，不证明原生 hold 消费。真实到期删除、任务导出生命周期、J8 原生必要调用故障腿、桌面通知视觉确认和其他平台仍待。九格 × J1–J11 没有 complete_acceptance，N09 保持 partial；T01–T06 门槛不变。

## 11. 个人门槛关闭后的团队目标（T01–T06）

这一节是保留的最终路线，当前不得提前计入开发完成。T01–T06 复用现有 `apps/control-api`、Worker、PostgreSQL、Edge/Connector 和企业 Web，不导入兄弟仓库内部实现。

| 批次 | 需要实现 | 必须验收 |
| --- | --- | --- |
| T01 局域网部署 | PostgreSQL 迁移、TLS/已验证身份、管理员、健康与备份恢复；设备主动出站；个人管理 API 保持 loopback | 至少另一台真实设备安全连接；错误证书/身份拒绝；生产不依赖 SQLite、自动建表或开发身份头 |
| T02 加入与设备身份 | 用户确认、限时单次接入码、注册/心跳、哈希凭据、撤销/退出/轮换/重装 | 并发重放、过期码、跨团队身份拒绝；退出不恢复撤销授权；离线撤销边界明确 |
| T03 资产与隐私 | tenant/device/instance/安装身份键；同名分离、增量/删除/失联、最少上报、角色可见性 | 两设备同名不覆盖，乱序/重连不复活资产；默认不上报秘密、原文或完整私有路径 |
| T04 定向与批量任务 | 目标设备、固定目标快照、父批次/子任务、lease/claim/ack、幂等/取消/部分成功 | 设备不能领取他人任务；并发/重复回执/断网重领可恢复；投递去重不冒充副作用 exactly-once |
| T05 组织策略生效 | 发布者/目标/版本/期限/签名、个人与组织权限交集、读回、撤销及离线期限 | published/received/applied/verified 分离；篡改/旧版本/错目标拒绝；两设备实际阻止越权 |
| T06 两设备综合验收 | 加入→资产→定向/批量→策略→离线重连→吊销退出，部署运维手册 | 至少两台真实设备，优先不同 OS；模拟压力只证明所测容量，不能替代实机 |

所有租户信息由已验证身份派生；设备凭据吊销在线请求即时复核；权限变更与审计/outbox 同事务，失败关闭。设备离线时无法即时接收撤销，必须描述可信缓存期限和恢复规则。团队管理不能使本地管理口公开，也不能让个人授权突破组织上限。

## 12. 验证命令与证据格式

按实际改动运行，有失败先定位，不为凑数量重复无关测试。以下命令在指定目录执行；依赖使用已有锁文件，不提交 node_modules、venv、二进制或个人状态。

```bash
# 仓库根目录
git diff --check
python3 scripts/check_ci_action_pins.py
python3 scripts/check_site.py
python3 -m unittest discover -s scripts/personal-experience/tests -v
python3 -m unittest discover -s scripts/personal-experience -p 'test_n09_evidence.py' -v

# apps/agentshield
gofmt -l .
go vet ./...
go test ./...
# 按触及范围选择关键包；授权/状态并发不得省略 race
go test -race ./internal/receipt ./internal/state ./internal/skillinstall ./internal/server

# apps/web
npm ci
npm test
npm run build
npm run build:local

# apps/control-api；只改合同可使用 --noconftest 的独立合同测试
uv sync --dev --locked
uv run ruff check app
uv run pytest --noconftest app/tests/test_schema_contracts.py app/tests/test_update_schedule_contracts.py
# 若改 Control API 实现/数据库，还须执行完整 uv run pytest 及对应迁移回放。
```

四目标 CGO=0 构建在 `apps/agentshield` 执行，输出到独立临时目录；Linux amd64/arm64、darwin arm64、windows amd64 均保留。构建前完成 Web embed 更新，记录实际产物 SHA256，不覆盖已安装程序。

浏览器 runner 在仓库根目录执行，传入自己刚构建的真实二进制和全新证据目录：

```bash
python3 scripts/personal-experience/session-browser-smoke.py --binary /absolute/path/to/candidate --out-dir docs/evidence/personal-experience/BATCH/browser-session --discovery
python3 scripts/personal-experience/update-check-browser-smoke.py --binary /absolute/path/to/candidate --out-dir docs/evidence/personal-experience/BATCH/browser-update-check
python3 scripts/personal-experience/n09-baseline-check.py --matrix /absolute/path/to/matrix.json
```

`BATCH` 和候选路径必须自行填写；不存在的环境先安装依赖或记录阻塞，不用删断言获得绿灯。需要真实宿主的 runner 先检查其 `--help` 和代码是否仍依赖被暂缓 N05/N06 接口。不得默认启动计费模型；需要调用时先向维护者说明模型、用例和费用范围。

每批证据至少包含：

- `report.md`：目标映射、问题、实际行为、关键安全不变量、尚未完成项及下一批。
- 版本化验证结果或准确现有格式：命令、cwd、退出码、开始结束时间、环境/版本、预期与实际、证据分类。
- 候选代码身份、未提交源码摘要（若有）与二进制摘要；组件 fixture 明确注明，不能标原生。
- 负向及恢复证据、真实副作用计数/文件前后差异、脱敏日志、精确清理记录。
- SHA256 清单及引用；机器消费新增格式先写 schema。跨 Windows 的被哈希材料使用有范围的 Git 字节保留规则，不通过改摘要掩盖 checkout 变化。

历史失败材料保留；新测试产生新的结果，不改旧报告身份。截图只辅助证明 UI；通过一条命令不能推导未执行能力。安全扫描发现问题先定位，不新增宽泛忽略、不取消密钥扫描、不删除负向用例。

## 13. 每批交付、进度与合并

1. 一批只关闭一个可明确验证的行为或子目标；先规格/合同，再实现、必要测试、UI 和证据。合同独立 `contracts:` 提交，业务提交遵循仓库 scope。
2. 改动完成后自己检查 diff、未跟踪文件、引用、秘密、生成资源和平台影响；不得留大量成果仅在记忆文件里。
3. 更新本书对应 R/N 状态及 `personal-experience-closure-progress-20260913.md`，指出哪部分代码完成、哪部分组件验证、哪部分原生验收和哪部分已合并。不得用提交数或测试数当总体百分比。
4. 按维护者在当前窗口给出的提交授权交付小 PR；只有最终 HEAD 所需检查通过且安全审阅完成后才能合入。不能用前一提交绿灯、免审标记或改保护规则替代验收。
5. 外部环境阻塞时写清解除条件、负责人、已完成的可复用材料，继续其他无依赖个人任务；不以等待 OS 为由停掉全部工作。
6. 不自动发布、改仓库设置、强推、删除其他人分支或发送协作消息。开发/实测授权不等于正式发行授权。

“代码已落盘”“本地验证通过”“已提交”“已推送”“已合并”“已发布”必须分别报告。R01/R02 在组件完成但真实调用链未验时保持 partial；N09 未关闭则不能宣称个人版或全部目标完成。

## 14. 可直接交给 GLM 的启动指令

> 请执行本任务书 v4.1，先按第 4.1 节识别接续工作树与未提交成果，读取第 3 节当前状态及第 15 节融合计划。继承 R01/R02 的 SEC、可信预留和原生证据，不重做已完成实现，也不把旧 N05/N06 的宽松匹配搬回。按 O00–O04 加固现有 OpenShell 适配器并测量原生路径基线；随后补 R03–R07 的 Linux 来源、生命周期、更新、隐私与完整用户旅程。O05 已配置实例会话依赖安全门槛及真实后端；O06 凭据扩展为条件任务。Windows sunbo 与 macOS Luke 的原任务不变。每批先规格/合同、后实现和正负向验证，记录证据级别、阻塞解除条件与提交状态；不绕过 N09 进入 T01–T06，不擅自发布。

## 15. 轻量化与 OpenShell 融合执行计划（2026-09-15）

### 15.1 文档职责与全局约束

[优化方案](SIQ_轻量化安全与OpenShell接入优化方案_20260914.md)全文纳入架构参考；其中历史版本依据与 R01/R02 待办描述保留来源含义，当前执行顺序和状态以本节及第 3 节为准。具体安全语义落入 [客户端安全合同 v2](../packages/contracts/openshell-policy-safety.v2.md) 与 `agentshield-dev-spec-v1.md` §3.9。三者冲突时先修正规格和任务状态再写代码，不能让架构建议自动成为已实现能力。

1. 默认个人模式继续使用 Go 本地服务与 embed UI，不依赖企业 Python 服务或 OpenShell；未启用时零额外 OpenShell 子进程/请求。
2. OpenShell 是可选执行后端；明确 required 的会话在后端失联或能力不足时失败关闭，不切回不受限 native。不新建沙箱、凭据库、任务聊天台或全局代理。
3. 复用 SEC、Intent/Authority、hold reservation、效果证据和现有安装事务。授权、执行、证据是职责边界，不是三个新增常驻服务。
4. 配置读取、配置生效、实际阻断和终端效果分别记录；CLI 存在、版本号、历史文档及成功响应不能证明内核隔离或副作用完成。
5. P0 属现有安全修复；可选执行和凭据扩展不改原 N09 分母、不新增团队阶段的隐式前置条件。若发行包含可选模式，必须同时通过该模式验收才能宣称支持。

### 15.2 批次、依赖与交付

以下 O 编号用于本书调度，对应优化方案原 P 编号；不是新产品目标分母。共享核心由当前维护者负责，后续可交 GLM/Codex 接续；平台负责人保持第 4.3 节不变。

| 批次 | 来源与依赖 | 精确工作范围 | 完成条件 | 初始状态 |
| --- | --- | --- | --- | --- |
| O00 基线与合同 | P0-0；无外部前置 | 固定源码状态、现有测试、Go/Python 差异、B0 测量；保留方案来源、定义 v2 安全语义 | 可复跑命令、环境和测量原始数据；不把旧二进制证据用于新候选 | doing：A–E 组件预算复测全部通过；新增独立 git archive 的 O04 增量真实 HTTP 对照，每版本允许/撤销后拒绝各 600 样本、增幅≤10%通过，记录 CPU/RSS/磁盘写入/请求数。基线为 O01–O03 后的 6e34f3a，不等价完整优化前 B0。完整 B1−B0、真实 OpenShell B2/B3 仍待；禁止 reset 不阻止独立基线工作。[复核报告](evidence/personal-experience/openshell-o04-review-20260915/report.md) |
| O01 策略保真 | P0-A/B/F；O00 | Go `policy.go/yamlkit.go`、Python `cli_backend.py/policy_compiler.py`：完整静态字段保留，严格 revision，拒绝 deny/L7/未知语义损失，按实际静态差异规划 | 两语言共享向量；强 Landlock/扩展字段不降级；缺失 revision/重复键/未知限制零写入；全策略摘要读回一致 | 实现、组件验证和隔离 OpenShell 0.0.83 真网验收完成：[O01/O02 报告](evidence/personal-experience/openshell-o01-o02-20260915/report.md)；真实 revision `7→8→9`、base/final 完整摘要一致；提交状态以 Git 历史为准 |
| O02 事务与回滚 | P0-C；O01 | 真实 base snapshot/revision/full digest、不可伪造操作绑定、目标串行、前后读回；回滚复核当前授权和漂移 | no-op 零写；非连续 revision 正确；伪造/重启后未知记录/外部漂移拒绝；撤销权限不复活 | 实现、组件验证和隔离真网验收完成：[O01/O02 报告](evidence/personal-experience/openshell-o01-o02-20260915/report.md)；仅进程内串行，后端无原子 CAS，不宣称跨进程原子事务；提交状态以 Git 历史为准 |
| O03 子进程边界 | P0-E；O00，可独立于 O01 | Go/Python CLI 及 Docker 发现共享输出字节上限、运行中限流、超时/管道等待有界、精确 env 白名单、稳定脱敏错误 | stdout+stderr 合并恰限通过/+1拒绝；持续输出、管道占用、超时、秘密 canary 负向；四目标构建 | 本地实现/验收完成：[报告](evidence/personal-experience/openshell-o03-20260915/report.md)；跨 OS 实机待补；提交状态以 Git 历史为准 |
| O04 当前能力与性能 | P0-D/性能；O01–O03 | 历史能力依据与当前身份/版本/行为证据分离；冻结 B1−B0 预算并采样 | 伪网关/旧文档不提升能力；未启用零后端进程；测量尾延迟、失败率和资源，记录缺项 | 本机复核修复完成，整体 doing：配置能力替代旧布尔编译判断；两语言共享 11 条 status 向量；缓存漂移/失败降级；目标只读 doctor 和 UI 过期显示；RSS v2 不可得为 null。D 180 样本 p95=200.886ms、max=201.261ms，原预算不变且通过。新增服务级 fixture 原生 HTTP 旅程，OpenShell/Docker Runner 调用为零；不宣称真实宿主或 OS 进程树验证。完整 B0、B2/B3 和跨 OS 实机待补。[复核证据](evidence/personal-experience/openshell-o04-review-20260915/report.md) |
| O05 可选已配置实例会话 | P2，继承 P1；O01–O04＋真实后端 | 固定一个实际可用版本和 Linux 驱动；预览/确认、实例身份、策略摘要和会话绑定；复用 SEC/预留；停止与不确定恢复；UI 解释保护边界 | 真实允许/拒绝及副作用证明；required 失联无 fallback；会话不可越界复用；native 无回归；只操纵明确归属实例 | blocked：当前网关不可达，版本/驱动待实测 |
| O06 凭据与指定目标出站 | P3；O05＋明确产品需求 | 现有 provider 的凭据引用和目标/动作绑定，必要时可选 L7 桥；不存明文，不用通用 exec 绕过结构化工具约束 | 合成 canary 不出现在错误/日志/导出/非法目标；DNS、重定向、代理及方法变更真实负向；覆盖范围明确 | conditional：不作为首版强制项 |

O01/O02 不得用“网关会拒绝”替代客户端拒绝。未实现原子 CAS 的后端只可声明进程内串行＋写前/写后漂移检测；跨进程外部写者仍可能竞态，不能标记原子事务。进程内回滚记录丢失时安全拒绝，持久化恢复需要另立状态合同与迁移方案。O03 只清理拥有的子进程/管道，不使用全局 kill；无法证明后代进程全部结束时保留限制，不宣称完整进程树隔离。

### 15.3 R 批次接续与平台分工

- R01/R02：已完成组件与部分 Linux 原生证据按第 5.4/6.4 节继承。O05 只补 backend/session/最终参数/策略修订绑定和失联恢复，不新造另一套批准令牌。
- R03：生产 Git 仍待合规直连网络；不改 SSRF/DNS 防护以制造正向证据。
- R04：继续 OpenClaw 原生 Skill V1→V2、来源关闭/确认变化、移除及隐私控制；Hermes 已有证据作为回归基线。2026-09-15 glm-linux 批次已完成 Linux/OpenClaw 原生 V1→取消→确认更新 V2→重授权→移除（见第 8.4 节）。
- R05/R06：本机补安装→配对→后台服务→重启/故障恢复→升级→保留数据卸载；Linux WorkBuddy 无真实运行时则保留 blocked。2026-09-15 复核补齐 runtime 服务保留状态重入，正式包升级与串联验收仍待（见第 9.2 节）。
- R07：补浏览器与真实宿主串联旅程、原文开启/到期/撤销/导出、通知实际可见性。2026-09-15 复核以新候选修复 UI 竞态并重跑真实浏览器/宿主旅程，覆盖边界与新矩阵见第 10.2 节；重建最终候选后逐行补证据，不修改旧报告的二进制身份。
- sunbo/Luke：继续原 Windows/macOS 三宿主任务，原生/WSL2/容器和架构分别登记。OpenShell 可选模式另列运行环境和证据；没有该环境不阻止原任务开发，也不得标该模式支持。
- T01–T06：仍严格服从第 10/11 节门槛；可选 P3 的缺席不自动阻塞团队，原 N09 缺项也不因 O 批次完成自动通过。

### 15.4 A01–A15 与原 N09 的覆盖关系

此表是测试追踪关系，不是 J 行完整验收的替代物。任一 A 用例只关闭它实际测到的范围；原 J1–J11 编号与要求保持不变。

| A 用例 | 对应批次 | 关联 J 行 | 必须保留的边界 |
| --- | --- | --- | --- |
| A01 原生未启用 | O00/O04 | J1/J4 | 原生旅程与零后端调用需同时观察 |
| A02 required 失联 | O05 | J3/J8 | 明确拒绝且无原生回退 |
| A03 上下文重放 | R01/O05 | J4/J7 | 同调用绑定，不能借用权限 |
| A04 批准后变更 | R02/R04/O05 | J4/J5/J6 | 最终参数、版本和撤销全部复核 |
| A05 并发与恢复 | R02/O05 | J5/J9 | 计数副作用；不确定不能盲重试 |
| A06 静态保真 | O01 | J4 | 完整语义或拒写 |
| A07 不支持限制 | O01 | J4 | 不静默转换成 allow |
| A08 回滚与漂移 | O02 | J4/J9 | 精确 base，不按 revision−1 |
| A09 能力误报 | O04/O05 | J3/J4 | 读回不代表内核阻断 |
| A10 秘密 canary | O03/O06 | J11 | 合成秘密，全出口扫描 |
| A11 出站绕过 | O05/O06 | J4/J8 | 只对实际声明范围取证 |
| A12 伪成功 | R02/O05 | J7 | 接收/终端证据独立验证 |
| A13 停止/失联 | R05/O05 | J8/J9/J10 | 拒新动作；已发动作可 uncertain |
| A14 输出/管道 | O03 | J8/J9 | 资源等待有界，不误杀 |
| A15 性能 | O00/O04/O05 | 横切全部旅程 | 性能报告不能代替任一功能行 |

### 15.5 测量、证据与退出条件

性能配置保持 B0（改造前 native）、B1（改造后 native）、B2（同 OpenShell 环境测试基线）、B3（新集成）。B2 不进入生产开关。先记录配置、源码/二进制摘要、机器、并发数、预热、样本量和原始样本，再冻结门槛；P95 +10% 只是方案建议，极短操作须另设绝对预算，不能事后改门槛使失败通过。B2/B3 缺真实后端时标 blocked。

每个报告分别记录 cold/preparation/hot/effect/user/external 时间、P50/P95/P99、CPU/RSS/写入/进程/请求计数、合法成功和误拒率；没有测到的指标写 not_measured。组件微基准不能冠名端到端性能。不得缓存已撤销授权或省去最终参数校验来提速。

每批证据落 `docs/evidence/personal-experience/openshell-<batch>-<timestamp>/`，包含报告、可重跑命令、版本/摘要、脱敏结果与限制；修改过的候选须重新验证受影响行。测试替身、真实子进程、真实网关、OS 实机分别标明；不因 42 项旧测试通过就把本节 O01–O06 标完成。

交付顺序：O00 → O01/O02/O03 → O04；穿插无依赖 Linux R03–R07 收口；具备真实条件后 O05；O06 按需求启动。每个子批次独立验收和更新状态，提交/合并/发行另按用户授权执行。
