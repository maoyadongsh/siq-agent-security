# SIQ 轻量化安全与 OpenShell 接入优化方案

日期：2026-09-14。性质：架构与开发建议，不是已经实现、部署或通过测试的功能说明。

## 0. 依据与范围

仓库只读核查基线：`b303c6f92392f3a44c306d81ad7323c6291ef4f2`。最新 v4 任务书的实现基线为其父提交 `4464dfbc8e66c8ec1fb2590b286351595fcd9667`。本文没有修改远程仓库、产品配置、研究发布快照或匿名投稿 Artifact，也没有重新执行该版本的测试或性能实验。

证据分为：S（本轮检查到的源码）、D（仓库任务书/历史记录）、U（OpenShell 官方当前文档）、P（本方案提出的设计）。D 中记录的历史验收不等于本轮复现；U 中描述的能力不等于 SIQ 适配器已支持。官方文档本轮显示 v0.0.116，仓库适配器包含更早 v0.0.83/v0.0.104 的能力依据，必须分开处理。

**总决策：继续现有 Go 本地服务和原生接入；先完成可信 Skill 归属与审批重试，修正现有 Go/Python OpenShell 适配器的策略往返与能力描述，再提供可选、按会话接入的 OpenShell 执行路径。不要另建沙箱、Vault、网关、调度平台或聊天工作台。**

## 1. 实际基础与缺口

1. 本地 Go 已有 `internal/openshell/{client,command,policy,diagnose,types,yamlkit}.go`，不是零接入。它能探测、执行网络策略 set 和配置读回，拒绝 create_generation。
2. 企业侧已有 `apps/control-api/app/adapters/openshell/` 的 EnforcementAdapter、编译器、CLI 后端、合同与测试。该接口主要是策略治理，不是已经完成的任意工具执行 API。
3. `ToolGateway.call` 已复制候选参数、在线请求决策、检查参数变换；`resume` 复查原始调用和当前授权；finally 路径保留观察处理。这些应复用。
4. PBA matcher 已检查所有提交的引用，并在一次图遍历中复用节点；不能将优化简化为“找到一个合法来源就通过”。
5. 最新 v4 任务书明确旧 N05 Skill 归属与 N06 审批重试实现未获接受。N02 生产 Git 仍关闭；N09 仍 partial；Windows/macOS 完整用户旅程不得按零散成功记录宣布完成。
6. 当前 OpenShell verify 只比较配置，属于 readback_verified；不是行为验证，更不是 EVC 的任务完成证明。
7. native 桌面路径仍是 same-UID 信任边界；不能因进程分开就宣布防御任意同用户恶意进程。

## 2. 必须守住的产品边界

默认路径不得新增必装的 Docker/Kubernetes、PostgreSQL、Redis、独立凭据服务、消息队列或 gRPC 守护服务。OpenShell 是显式选择的外部后端：用户已经选择受保护执行的任务，在后端不可达、能力未知或策略失配时不得静默回退到本机不受限执行。原生兼容模式可以继续存在，但 UI 必须显示其实际保护范围。

所谓三平面只是信任职责：
- 授权：现有 SIQ Go Runtime、Grant/Intent、来源与审批；
- 执行：既有宿主工具，或用户选定的 OpenShell 沙箱；
- 证据：已有 Receipt、观察者、EVC。

不为这三个词新增三个服务。个人安装不得以企业 Control API 作为工具调用必经点。团队阶段继续遵守 v4 的 N09 前置门槛。

### 推荐首版拓扑

```text
用户原生 Agent 界面 / Harness
               |
         已有宿主适配器 / ToolGateway
               |
   SIQ 本地 Runtime：PBA / 审批 / 撤销 / 调用绑定
               |
      +--------+---------------------------+
      |                                    |
注册的结构化工具                    可选 OpenShell 执行
明确参数、有限凭据引用               不可信代码/命令/依赖处理
      |                                    |
受控服务请求                         默认受限网络、文件、进程
      +----------------+-------------------+
                       |
        普通工具报告 与 合格观察材料分别入库
                       |
                     EVC
```

结构化外部工具必须是可信执行器，不在宿主直接执行任意生成代码。读取也可能接触秘密；不得仅凭 read/GET/ls 标签跳过权限校验。无法可信地接管最终执行点的宿主，不标记为已完成隔离执行。

## 3. P0：先修现有适配器，而不是扩功能

以下为源码层面发现及待验证风险，不等于已完成漏洞利用或故障复现。

### P0-A 完整策略往返与静态字段保留

涉及 Go `internal/openshell/policy.go`、`types.go`、`yamlkit.go`；Python `cli_backend.py`、`contracts.py`。

当前 Snapshot 只投影文件、网络、进程等字段；网络更新会重新写入 `landlock.compatibility=best_effort`。如果原策略有不同 Landlock 要求或其他扩展，可能造成意外拒绝或语义改变，不能声称是完整静态保留。

实现要求：保存经过校验的原始完整策略、策略摘要、静态部分摘要和真实 revision；仅更新明确拥有且受支持的网络子树。无法无损处理的字段必须拒绝写回，不能忽略。读取不到 revision 时返回 unknown/错误，禁止默认填 1。写回后对完整期望策略而不只是 host:port 集合进行读回比较。

对于新增严格隔离配置，在后端确认支持且文件路径有效后使用 hard_requirement；现有 best_effort 安装不得未经用户确认全局改档。不支持严格隔离就明确 unavailable，不能自动降级。

### P0-B 编译语义不能无声丢失

Go `networkRulesToGateway` 当前转换过程中没有读取 `NetworkRule.Effect`。需先检查调用入口约束，并在转换层补测试：deny 要正确执行或明确拒绝，不能被序列化成 allow。对 method、path、binary、协议、provider binding 也采用相同原则。

旧的 host:port 投影不得用于宣称完成 L7 规则比较。缺 binary 不能在新严格配置下默默扩为默认执行程序；历史兼容默认值要明确记录并经用户确认。Python 编译器的 unsupported 项必须与最终部署阻断/其他可信执行点覆盖共同关联，不能仅在 UI 提示后继续落地一个不完整权限策略。

### P0-C 回滚绑定真实变更前快照

Go 与 Python 当前回滚以回执 revision 减一寻找旧策略。改为保存 base_revision、base_policy_digest、applied_revision、applied_digest、操作身份与结果状态。

no-op 的回滚仍应 no-op。发生带外变化时不得覆盖第三方修改。恢复的是经过核对的本次变更前策略，不是算术上的前一编号。回滚若重新扩大权限，应重新经过当前上限/撤销检查；回滚配置不能恢复已经撤销的 Grant。

优先使用目标版本原生条件更新。后端无原子 CAS 时，限定单写者，使用目标级互斥、写前读回、写后核对；明确这不等于跨外部写者的原子事务。异常时停止新任务准入、显示漂移/恢复待确认。

### P0-D 能力探测分清历史依据和当前状态

当前 Go 已增加 live status 握手，不能再把 gateway info 当作唯一活性判断。保留此修复；能力布尔仍主要来自历史常量。

能力记录建议在现有合同中版本化扩展：后端实例身份、CLI/网关/supervisor 版本或摘要、驱动与内核特征、配置摘要、观察时间、证据类型、支持范围和失败原因。握手成功不证明 Landlock/L7/凭据隔离生效。

保留 supported/unsupported/unknown 与 enforce/observe/advisory/none；另外记录验证层次，不能用 supported 一词同时表示语法存在、配置读回与真实行为。未报告的新能力不得自动提升。路径上限等数字没有本版本依据时不要填历史默认值为实测上限。

### P0-E 子进程边界有界且少泄露

Go 当前在 strings.Builder 收集完整输出后才比较 MaxOutput；Python capture_output 同样需要执行期间的容量限制。改为 stdout/stderr 共享总预算、达到上限立即取消并按已验证平台机制清理受管子进程，等待收敛时间有界。兼顾超时、子进程持有管道、并发输出与取消。

环境变量从任意 SIQ_AS_/OPENSHELL_ 前缀透传，收紧为逐命令必要键白名单；CLI 配置目录必须是可信私有目录。兼容 env.sh 仅供明确选择的可信部署，不能从候选仓库发现后执行。错误以稳定 reason_code 返回；秘密、完整私有地址、参数正文和原始 stderr 不进入普通日志。

### P0-F 不因存在静态字段就重建

Python compile_policy 目前看到 filesystem/process 即置 needs_generation。下一版应由真实静态语义差异决定：静态内容未变而只变网络，不重建；静态内容变化则使用经验证的 generation 流程，未支持则拒绝。本期不为此开放尚未验收的生命周期功能。

## 4. R01/R02：可信调用关联与一次性审批

沿用 v4 的 R01/R02，不新建审批引擎。

### R01

可信上下文至少绑定：平台实例、认证主体、session/task/tool_call ID、工具名、最终参数摘要、Skill 安装身份与内容修订、Grant/Authority 修订；启用 OpenShell 后增加不可复用的 sandbox ID、generation 与策略身份。

字段齐全不等于可信：issuer 必须是可信宿主控制点或经认证的桥接端，不能由模型、自报 header、cwd、安装摘要自行证明调用归属。适配器不得获得 SIQ 状态签名私钥。跨 Skill、跨会话、跨任务复制合法上下文必须拒绝。

有效权限采用已证明身份对应的 Agent/Task/Skill 限制与后端允许范围的交集。未知 Skill 不获得 Skill 专属权限；也不能通过删除 claim 逃离已知的限制。不实现完整语义因果重建，不谎称知道任意模型推理的全部来源。

### R02

`ReadHoldStatus` 是在线查证，不是新执行租约，也不是审批消费动作。保留其当前参数、会话、Intent、Grant、来源复查。

在现有回执/状态存储中实现显式一次消费和执行关联，建议概念状态：pending → approved → dispatch_reserved → dispatched → observed；另有 denied/expired/revoked/dispatch_unknown。具体命名需先与现有 schema 兼容。

一个审批只对应被批准的动作实例。并发重试不能各自执行；服务重启不得复活已消费授权。执行后回执丢失时使用外部幂等键/查询或人工核对，不盲重放。未控制远端事务时，不承诺全局 exactly-once。

## 5. OpenShell 首版：只接已配置实例

复用 Go `internal/openshell` 做个人端探测、目标确认、有限操作与读回；复用 Python 现有接口做企业策略治理。统一 schema、能力词汇、固定输入输出测试向量，不强迫个人端安装 Python 企业服务，也不再增加第三套策略编译器。

第一版仅支持一个经验证的 OpenShell 版本范围、一个执行驱动、明确的 Linux 执行环境。Windows/macOS 可作为客户端或后续原生宿主验收项，记录 host_os、execution_os、architecture、driver，不能把 WSL/容器中的 Linux 结果写成 Windows/macOS 原生隔离。

用户流程：检测 → 展示现有网关/沙箱及能力 → 用户确认绑定 → 行为探针通过 → 会话内复用 → 任务结束清理或释放。初期不安装 OpenShell、不自行启动未知网关、不修改全局 Docker、不自动接管扫描对象、不建预热池。

受保护任务开始前确认后端身份、当前策略与任务要求。会话复用键至少包含主体、工作空间、任务信任范围、静态策略、凭据集合/版本和数据敏感域；不跨用户或不相关任务共享脏沙箱。任务结束只处理受管临时实例与目录，用户文件保持不变。

## 6. 网络与凭据：首先让高影响动作走结构化工具

### 首版边界

OpenShell 处理不可信代码/命令的环境约束；发布、消息发送、权限修改等高影响外部动作通过 SIQ 已登记的结构化工具。沙箱不能同时拥有绕过这些工具的通用高权限 SaaS 出口与令牌。

仅允许访问某 API host/POST，不能替代 recipient/repository 等参数的来源授权。只读 GET 也可能通过查询、路径或请求体泄露数据。外部目录/依赖访问必须同时考虑所持数据与来源策略。

初始化依赖尽可能在没有用户秘密和敏感数据的受限准备阶段完成，固定内容身份；任务阶段切换到更小权限。准备阶段本身不是可信区，安装脚本照样不可信。策略切换须确认已生效，不能边运行敏感任务边等待降权传播。

### 凭据原则

SIQ 管理/签发私钥和 OpenShell 管理凭据不得进入不可信子进程或挂载目录。优先复用 OpenShell Provider/已存在凭据系统，SIQ 保存引用和用途约束，不保存第二份通用秘密库。真正秘密只能由授权的执行边界在目标匹配后使用。

OpenShell 最新 Provider 文档描述占位符与请求时注入，但当前 SIQ 能力仍未实测；只有版本固定、负向 canary、目标/方法/路径/主体绑定和响应泄露检查通过后，才启用相应能力。启用 provider 自动贡献网络规则时，验证全部合成策略，不只验证 SIQ 自己提交的子树。

### 后续可选 L7 桥接

只有当真实业务必须允许沙箱内直接访问受权限保护 API，才评估 Supervisor Middleware。它与 Gateway Interceptor 不同：前者是已获网络准入请求的出站检查，后者主要是控制面变更。不能将任一 hook 宣称为自动覆盖全部工具与结果。

新增桥接端必须把经认证 sandbox ID 映射到 SIQ 会话；验证动作/参数摘要、受众、时效和当前授权；不能信任调用方自报 ID。PBA 检查后任何业务参数变换必须重新查证。流式/二进制/不支持的协议显式标覆盖缺口。

外部 middleware 的依赖和部署成本须先有 ADR。Go 核心保持 stdlib；桥接作为可选组件，不放进默认任务热路径，不引入每请求 LLM 判断。

## 7. EVC、日志与停止

网络配置读回≠真实阻断；代理转发≠远端业务完成；普通工具成功≠合格独立观察。OpenShell 日志先作为运行观察，不能直接换标签成为 EVC 的独立效果证据。

新增观察器复用现有准入与关联逻辑，保留 action/decision/task/intent、资源、内容摘要、观察域和覆盖范围。观察器应在不可信执行权限之外；native 模式不因此获得任意 same-UID 攻击隔离。

按可信 Intent 声明的要求收集证据，不对每个系统调用建独立业务证明。不降低现有完成语义；没有要求的场景按现有 not_required 行为，不显示伪造 VERIFIED。强制效果证据未到不能提前宣布完成。异步化只适用于不影响授权/状态一致性的展示和派生索引。

停止要区分授权撤销、阻止新请求、终止执行与观察收尾。先持久化撤销，再取消待执行动作、调用后端关闭相应网络/凭据路径与受管执行，最终读回。网关失联不能自动等于所有沙箱已停止；状态显示 stop_requested/stop_confirmed/stop_unconfirmed（建议名字），不虚构瞬时全局停止。已发生远端效果不能通过 kill 撤回。

## 8. 性能方案：省重复工作，不省必要检查

### 热路径限制

- 未启用 OpenShell：新增 OpenShell 子进程、网络请求、后台依赖为零。
- 一次任务/会话准备，多个调用复用；不每个 ls 重建沙箱。
- probe、policy set、完整配置读回放在会话准备/变更/漂移诊断路径，不每个工具调用启动 CLI。
- 每个受保护调用继续校验身份、动作/参数绑定、当前强制权限与撤销。
- 不缓存最终 allow 后忽略新撤销/状态变化。可缓存不可变解析和编译结果，键绑定版本、内容摘要、签发者/注册表修订和作用域。
- 当前 matcher 已有单次遍历复用；跨请求缓存先测量、再单独设计。
- 当前 Gateway 审批等待轮询间隔0.2秒；先加取消/退避/抖动、去重等待。需要时复用事件通知，通知只触发查证而非直接放行。
- 证据解析与 UI 投影可去重；安全回执持久化、授权和消费状态不得随意异步化。磁盘瓶颈必须用 profile 证明后优化。

### 测量协议

建立四种隔离实验配置：B0 当前 native；B1 改造后的 native；B2 相同 OpenShell 环境和任务、不含新增 SIQ 集成步骤的受控测试基线；B3 新集成。B2 只在测试夹具使用，不提供生产绕过开关。

比较 B1−B0 的兼容路径回归，B3−B2 的授权与集成开销；另列冷启动、会话准备、热执行、效果等待、人工等待和外部服务时间。记录 wall-clock/CPU/RSS、磁盘写入、进程数、网络往返、P50/P95/P99、误拒和合法完成率。不要只用慢模型响应掩盖本地开销。

测试前固定工具链、OS/架构、候选摘要、任务输入、并发量和测量边界；随机交替配置顺序，分开 warmup 与采样，报告方差和失败。重复性能样本不当作独立安全任务。优先用较多轻量调用定位固定成本，再用完整开发任务验证体验。

建议初始门槛（不是实测结论，基线采集后确认）：B1 相比 B0 合法固定任务 P95 增幅不超过10%；接近零耗时的操作采用另行冻结的绝对预算；未启用后端零额外后端进程；不增加不必要的人审次数；安全负向必须零未授权副作用；内存有界，持续运行无增长趋势。不承诺一个未经本机验证的固定毫秒数。

## 9. 接口与状态变更原则

不从零发明执行授权协议。对现有版本化合同作最小扩展，建议逻辑字段：

```text
ExecutionBinding（建议，不是当前已发布 API）
  action_id / decision_receipt_id
  authenticated_subject / platform_instance / session_id / task_id
  tool / canonical_final_params_digest
  install_revision / authority_revision
  backend_instance_id / sandbox_id / generation_id
  effective_policy_revision / effective_policy_digest
  issued_at / expires_at / audience
```

字段不应全部从请求正文直接相信。验证方使用现有规范化/签名实现与可信状态读回。持久化写入口复用 stateformat/statefs；给旧版本提供显式兼容/拒写行为，不通过删除标记或迁移静默放宽权限。

状态合同保留三类独立结论：authority decision、backend enforcement verification、task completion。UI 可映射成“仅发现/已连接/配置已确认/指定行为已验证/本任务结果已验证”，禁止一个“已保护”绿标覆盖所有层次。

## 10. 最小验收矩阵

| 编号 | 测试 | 通过标准 |
|---|---|---|
| A01 | 原生功能未启用后端 | 原有合法任务正常；无 OpenShell 进程和后端请求 |
| A02 | Required 后端失联/未知能力 | 明确拒绝；不切回原生执行 |
| A03 | Skill/会话/任务上下文重放 | 不借用权限，未授权副作用为零 |
| A04 | 批准后改参数、版本或撤销 | 旧批准失效；显示准确原因 |
| A05 | 同一批准并发消费、重启恢复 | 单次准入；未知远端结果不盲重试 |
| A06 | 网络更新保留强静态策略 | Landlock/进程/文件和未触碰字段保持原义；不支持则拒写 |
| A07 | deny/L7字段进入旧转换器 | 正确表达或明确unsupported，不能变成allow |
| A08 | no-op/并发漂移后回滚 | 回到本次原始快照或拒绝；不回滚错revision |
| A09 | 读取成功但内核能力缺失 | 不标行为验证；严格配置无法启动 |
| A10 | 秘密 canary 暴露检查 | 子进程env/文件/日志/导出/错误均无真实值；非法目标无凭据 |
| A11 | 代理绕过、DNS、重定向及方法变更 | 在声明保护范围内实际阻断；不支持项显式标注 |
| A12 | 工具伪成功/无接收事件 | 保持未验证，不因代理成功而VERIFIED |
| A13 | 取消/停止、后端失联 | 拒绝新动作；停止确认与不确定分开；不误杀无关实例 |
| A14 | 超量输出与子进程管道占用 | 内存和等待有界；清理仅作用于受管对象 |
| A15 | B1/B3性能比较 | 达到冻结性能门槛，报告失败与尾延迟，不弱化安全检查 |

所有网络负向使用自有受控端点和合成秘密，不攻击真实第三方。测试上下文、期望、实际终端状态及证明范围分别记录，配置读回不可代替真实行为探针。

## 11. 分阶段 PR 与依赖

| 阶段 | 工作 | 修改面 | 出口条件 |
|---|---|---|---|
| P0-0 | 固定基线、协议差异和性能计时点 | 文档、fixture、测试 | 无行为变化；可重跑基线；数据边界明确 |
| P0-1 | 完整策略往返、revision严格解析、deny/unsupported保护 | Go openshell 与 Python adapter/contracts | A06–A09；两语言共用向量 |
| P0-2 | 变更前快照回滚、目标互斥、子进程输出和日志边界 | 上述客户端/状态层 | no-op/漂移/超限/超时负向通过 |
| P1 | 完成 R01/R02 可信绑定和一次消费 | 现有 receipt/state/宿主适配器 | 可信正向+重放/并发/失联零越权；不复用被否旧实现 |
| P2 | OpenShell单版本、已有实例的可选受保护会话 | 现有 internal/openshell、ToolGateway/宿主、UI | Linux真实小闭环；结构化高影响动作不被沙箱绕过；native无回归 |
| P3 | 凭据引用与指定目标直接出站集成（按需求启动） | Provider映射；必要时可选middleware桥 | 目标/动作/凭据绑定、canary、超时与协议覆盖测试通过 |
| P4 | Windows/macOS真实矩阵与产品旅程 | 各平台负责人、现有N09证据工具 | 与当前候选对应的逐行验收；不混用WSL/容器与原生 |

R01/R02 为当前既定优先级；适配器无语义损失等修复可并行，不抢占 N09 前的团队功能。共享核心由维护者协调，Windows/macOS 负责人只对实机执行过的范围签收。跨语言行为变化需共同 schema/fixture，不能各维护一份不同的安全含义。

首个可交付版本可停止在 P2，不强制完成 P3。只要严格限定出站能力，已有沙箱约束与结构化工具就能提供一条有用的轻量路径；无需先建通用网络审查服务。

## 12. 发布、回退与论文

新功能默认关闭；用户先看权限/执行范围预览再启用。能力不足显示具体缺项与排错，不用“已连接”暗示“已隔离”。功能回退只停止新模式的准入并恢复受管配置，不隐藏失败、恢复过期授权或静默换成不受限native。

每批结果记录独立源码、二进制、OS/执行环境、命令、退出码、案例来源和观察端点。现有冻结论文/研究归档不改写；新 OpenShell、Windows/macOS 或性能实验独立建身份，达到相应门槛后才更新公开能力矩阵。不能以本设计文档作为实验已完成的依据。

---

## 依据索引

以下 GitHub 链接固定于核查快照。官方 latest 链接会变化，实施时需保存实际版本与页面/协议快照。

- [S1 主线身份](https://github.com/maoyadongsh/siq-agent-security/commit/b303c6f92392f3a44c306d81ad7323c6291ef4f2)
- [D1 最新v4任务书](https://github.com/maoyadongsh/siq-agent-security/blob/b303c6f92392f3a44c306d81ad7323c6291ef4f2/docs/personal-experience-lan-team-next-development-taskbook-20260914-112027.md)：N/R优先级、可信归属/重试未验收、N09范围。
- [S2 Go OpenShell client](https://github.com/maoyadongsh/siq-agent-security/blob/b303c6f92392f3a44c306d81ad7323c6291ef4f2/apps/agentshield/internal/openshell/client.go)：live status与历史能力文档。
- [S3 Go OpenShell policy](https://github.com/maoyadongsh/siq-agent-security/blob/b303c6f92392f3a44c306d81ad7323c6291ef4f2/apps/agentshield/internal/openshell/policy.go)：静态投影、网络转换、读回、rollback。
- [S4 Go subprocess](https://github.com/maoyadongsh/siq-agent-security/blob/b303c6f92392f3a44c306d81ad7323c6291ef4f2/apps/agentshield/internal/openshell/command.go)：环境、超时、执行后输出限额。
- [S5 Python backend](https://github.com/maoyadongsh/siq-agent-security/blob/b303c6f92392f3a44c306d81ad7323c6291ef4f2/apps/control-api/app/adapters/openshell/cli_backend.py)：能力、完整策略写入、回滚、配置读回与事件范围。
- [S6 Python compiler](https://github.com/maoyadongsh/siq-agent-security/blob/b303c6f92392f3a44c306d81ad7323c6291ef4f2/apps/control-api/app/adapters/openshell/policy_compiler.py)：unsupported与generation判定。
- [S7 后端接口](https://github.com/maoyadongsh/siq-agent-security/blob/b303c6f92392f3a44c306d81ad7323c6291ef4f2/apps/control-api/app/adapters/openshell/base.py)：策略治理与验证分级。
- [S8 ToolGateway](https://github.com/maoyadongsh/siq-agent-security/blob/b303c6f92392f3a44c306d81ad7323c6291ef4f2/apps/secure-agent/secure_agent/gateway.py)：参数复制、在线审批复查、0.2秒等待循环、finally观察。
- [S9 PBA matcher](https://github.com/maoyadongsh/siq-agent-security/blob/b303c6f92392f3a44c306d81ad7323c6291ef4f2/apps/agentshield/internal/provenance/matcher.go)：所有已提交引用检查。
- [S10 Hold status](https://github.com/maoyadongsh/siq-agent-security/blob/b303c6f92392f3a44c306d81ad7323c6291ef4f2/apps/agentshield/internal/receipt/hold_status.go)：状态读回不授予新租约。
- [S11 Completion](https://github.com/maoyadongsh/siq-agent-security/blob/b303c6f92392f3a44c306d81ad7323c6291ef4f2/apps/agentshield/internal/completion/evaluate.go)：观察准入和状态优先级。
- [S12 模块约束](https://github.com/maoyadongsh/siq-agent-security/blob/b303c6f92392f3a44c306d81ad7323c6291ef4f2/apps/agentshield/AGENTS.md)：stdlib、分权、共享向量。个别旧条款与v4冲突时，需先同步规格，不能用旧Git条款解除N02生产门禁。
- [U1 OpenShell架构](https://docs.nvidia.com/openshell/latest/about/how-it-works)：CLI/Gateway/Supervisor职责及失联保留配置。
- [U2 策略schema](https://docs.nvidia.com/openshell/latest/reference/policy-schema)：静态/动态、Landlock严格性、L7字段。
- [U3 Providers](https://docs.nvidia.com/openshell/latest/sandboxes/manage-providers)：凭据绑定、provider策略贡献。
- [U4 Supervisor Middleware](https://docs.nvidia.com/openshell/latest/extensibility/supervisor-middleware)：出站时序、认证上下文及协议覆盖限制。
- [U5 Gateway Interceptors](https://docs.nvidia.com/openshell/latest/extensibility/gateway-interceptors)：控制面变更拦截，与工具数据面不同。

## 源码证据定位补充

P0-A/B/C 对应 S3、S5；P0-D 对应 S2、S5；P0-E 对应 S4、S5；P0-F 对应 S6；R01/R02缺口来自D1，已有复查来自S8/S10；性能缓存约束来自S9与安全设计推导。所有门槛、PR划分、会话策略、ExecutionBinding扩展与停止状态均是本方案建议，不是仓库已完成能力。
