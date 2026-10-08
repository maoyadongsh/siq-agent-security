# 安全优化实施进度（2026-10-07）

状态源：[optimization-tasks-20261007.json](optimization-tasks-20261007.json)。本文件为其阅读视图，更新状态先修改 JSON，再刷新本视图。

方案：[优化开发方案](SIQ_Agent_Security_优化开发方案_20261007-102651.md)。

基线：`c41347579ebe67c7f732d0e523722e489f831039`。分支：`codex/security-optimization-20261007`。

当前主任务验收：**11/16（68.75%）**。最新完成OPT-14；下方批次段落保留当时状态，不作为当前总数。

| 任务 | 内容 | 状态 | 旧任务映射 |
| --- | --- | --- | --- |
| OPT-00 | 基线与既有任务去重 | done | 本批新增／现有流程复用 |
| OPT-01 | 回执链并发一致性 | done | 本批新增／现有流程复用 |
| OPT-02 | 生产构建与身份边界 | done | 本批新增／现有流程复用 |
| OPT-03 | 扫描资源预算与限流 | done | SEC-F08 |
| OPT-04 | 错误输入与分页 | done | 待结合对应模块继续核对 |
| OPT-05 | OpenShell持久化回滚与后端绑定 | done | 待结合对应模块继续核对 |
| OPT-06 | pending提升幂等 | done | SEC-F05 |
| OPT-07 | 策略语义与部署入口 | done | 待结合对应模块继续核对 |
| OPT-08 | 日常Skill上下文 | implementing | 待结合对应模块继续核对 |
| OPT-09 | OpenShell行为证据 | done | 待结合对应模块继续核对 |
| OPT-10 | 同候选业务回归 | implementing | 待结合对应模块继续核对 |
| OPT-11 | 连接器可信执行 | implementing | 待结合对应模块继续核对 |
| OPT-12 | 钩子完整性 | implementing | 待结合对应模块继续核对 |
| OPT-13 | 交付安全头 | done | 待结合对应模块继续核对 |
| OPT-14 | 扫描进程隔离 | done | SEC-F08 |
| OPT-15 | 跨平台验收与有界清理 | implementing | SEC-F06 |

## 当前验证

OPT-01 首批组件与 OPT-02 生产身份边界已完成本批回归，见[首批验证](optimization-opt01-opt02-validation-20261007.md)及[消费者回归](optimization-opt02-consumers-validation-20261007.md)。前端 1,031 项通过；30 组浏览器脚本均有通过记录（首轮 28 组、修复复跑 2 组）。[OPT-04 验证](optimization-opt04-validation-20261007.md)包括控制面 2,346 项通过、1 跳过，PostgreSQL 19 项检查、本地 Go 全量与四目标构建。

[OPT-03 / OPT-14 验证](optimization-opt03-opt14-validation-20261007.md)：控制面 2,372 通过、1 个既有条件跳过；进程配额与原生 Linux worker 故障边界通过。默认 Docker 阻止 namespace 创建，OPT-14 保持 implementing；[OPT-06](optimization-opt06-validation-20261007.md) 来源事件幂等、v2 重启恢复及全套相关 race 已通过。[OPT-05 A](optimization-opt05-backend-validation-20261007.md) 原部署后端绑定已验证：控制面 2,383 通过、1 跳过，PostgreSQL 22 项检查；[B 批基础组件](optimization-opt05-journal-validation-20261007.md)已通过定向与 PostgreSQL 29 项检查，[在线持久恢复](optimization-opt05-online-validation-20261007.md)已完成：控制面全量 2,475 通过、1 条条件跳过，PostgreSQL 31 项检查、真实 OpenShell 14 项检查通过，包括新 API 进程精确回滚。未推送或完成主线 CI，不作最终发行或全部任务完成结论。

[OPT-07 验证](optimization-opt07-validation-20261007.md)：新增 15 条共享语义向量，四入口 32 项矩阵独立通过；Python 全量 2,486 通过、1 条条件跳过，PostgreSQL 31 项检查，Go 44 个测试包及 grant/server race、四目标构建通过。本地网络替换接口明确区分缺省/null 与空数组。

OPT-08 保持 implementing。[A 合同](optimization-opt08-context-validation-20261007.md)、[B1 持久上下文](optimization-opt08-store-validation-20261007.md)、[B2 精确调用](optimization-opt08-call-validation-20261007.md)、[C1 决策交集](optimization-opt08-engine-validation-20261007.md)、[C2a 审批重试](optimization-opt08-hold-validation-20261007.md)、[C2b 版本兼容](optimization-opt08-compat-validation-20261007.md)、[C2c 消费者兼容](optimization-opt08-consumers-validation-20261007.md)、[D1 签名身份策略](optimization-opt08-enrollment-validation-20261007.md)、[D2a 版本化读回](optimization-opt08-readback-validation-20261007.md)、[D2b Linux 宿主通道](optimization-opt08-channel-validation-20261007.md) 已完成各自组件验证。最新前端 1,082 项、相关 Python 合同 300 项、Hermes 身份 69 项、Go 全量和身份/请求定向 race、四目标构建通过。D1 的 340 项合同和 C2c 页面 HTTP 夹具结果按原批次保留。身份固定的必需策略已连接精确调用校验，未配置原生查询的 HTTP 明确拒绝新身份。原 v1 追踪投影明确标记无法表达的原生 Skill 来源 unavailable，完整证明保留在 v3 回执。版本化管理/运行读回已补齐；旧 Hermes 插件拒绝新会话响应。 D2b 经最终 31 项真实 Unix 凭据/进程测试（两个 Python 环境）、292 项相关合同以及固定业务镜像离线容器六项检查验证。可信启动器/制品与只读挂载核验、加载/调用事件、serve 接线和日常业务效果验收仍未完成；新身份的 HTTP 创建入口保持关闭。

[D2c1 文件快照](optimization-opt08-source-validation-20261007.md)已完成组件验证：47 项定向、230 项 Hermes 适配器全套、293 项相关合同通过；覆盖缓存内容漂移、路径替换、实际字节/文本摘要、回调失败和真实凭据通道传输。已核对固定业务镜像的普通/插件加载、缓存、预处理和最终分发位置，该批尚未修改原生函数，后续 D2c2 已接线。OPT-08 状态不变。

[OPT-13 交付响应头](optimization-opt13-validation-20261007.md)已完成：本地统一安全头、企业静态错误缓存修复；真实 HTTP 38 项（本地 14、企业 Nginx 12、代理链 12）及浏览器正负检查通过。本地配对、会话恢复、设置导航、退出正常；企业生产登录页正常。Go 45 包通过、10 包无测试，相关三包 race 和四目标构建通过。未宣称生产 Gateway/IAM 或完整 DNS rebinding 验收。当前主任务验收完成 9/16（56.25%）。

[OPT-11 连接器可信启动](optimization-opt11-validation-20261007.md)已完成 Linux 组件实现与一轮批次回归：Edge 689 项通过、2 项条件跳过，定向 race、vet、四目标构建通过。受管扫描、能力探测和 Skill 采集绑定确认计划、签名暂存包与实际程序摘要；Linux 保持文件描述符直至启动。正式签名包安装/升级和设备迁移未验收，任务保持 implementing，主任务完成数仍为 9/16。

[D2c2 原生 Hermes 分发](optimization-opt08-dispatch-validation-20261007.md)已落盘固定镜像补丁：普通/插件/缓存读取、任务作用域和中间件之后的实际 handler 门禁均接入；未接线的宿主直达路由明确拒绝。真实 Hermes 函数离线探针 21 项通过，构建器两个负向通过。全适配器首轮 252 通过、1 失败；已修复任务结束后的锁阻塞，受影响套件 24 项通过，未重复无关全量。探针采用合成 Authority 回调，没有真实 SIQ 在线裁决、OpenShell 或业务 API 验收；新身份创建仍关闭。OPT-08 继续 implementing，主任务完成数仍为 9/16。

[D2d 宿主应用桥接](optimization-opt08-host-validation-20261007.md)已串接原生生命周期与真实 Go 签名 Store/决策引擎：切换保留祖先权限，新独立任务能使用对应 Skill；重启后不能通过历史调用幂等读回重放执行。八组新增测试（含十八个负向子用例）通过；一轮全量 45 包通过、10 包无测试，最终增量相关三包、race、vet 和四目标构建通过。该批实际进程/安装解析使用组件夹具，安装解析随后由 D2e 增量补齐；认证传输、可信启动器及日常业务接线未完成，不将两个独立组件测试拼成端到端验收。OPT-08 状态和 9/16 完成数不变。

[D2e 实际安装来源](optimization-opt08-install-source-validation-20261007.md)已接入真实导入、批准、安装和运行绑定验证；真实 Python 读取器同步等待 Go 来源校验后返回正文。联验发现并修复了安装归属硬链接对与默认单链接读取限制的冲突：默认保持拒绝，受管模式显式启用且核对签名归属，额外链接仍拒绝。259 项 Hermes 适配器、Go 全量 45 包、两包 race、vet、四目标构建及固定镜像 21 项探针通过。实际进程/只读挂载仍需可信启动器，在线产品入口未启用；OPT-08 和 9/16 完成数保持不变。

[D2f 实际运行核验](optimization-opt08-runtime-guard-validation-20261007.md)已补齐真实进程、代码摘要和内核只读挂载检查，与真实凭据通道联验 21 项通过；错误启动参数、解释器/制品、文件变化、写挂载和覆盖子挂载均拒绝。仅运行本批定向探针与 Ruff，未重复未改动的 Go/Hermes 全套。Docker 后端仅为离线组件验证，OpenShell 启动归属、认证发布、serve 与日常业务仍待接入；OPT-08 状态与 9/16 完成数不变。

[D2g 在线宿主接线](optimization-opt08-online-validation-20261007.md)已接入显式启动、专用发布凭据、逐次私有通道回查、实际 HTTP 参数绑定及 Engine；deny/hold 关闭在途调用，重放与失联拒绝。Go 全量 45 包、定向 race/vet/四目标构建、Hermes 264 项统一回归、最终相关 5 项、6 项协议合同及镜像 21 项探针通过。不同组件的合成依赖明确分列，不冒充一条真实 OpenShell 业务验收；真实启动器/日常入口和审批重试交互仍待完成，新身份创建保持关闭，完成数仍为 9/16。

## 边界

既有 SEC-F01–F04/F07/F09 不因本方案自动插入；与实际修改相关时按原合同处理。RES-01 与 SEC-F10 的 Host Sensor 方向关联，但不自动纳入风险评分或强制执行实现。Windows/macOS 原生验收环境需在相应任务启动时核实，不以 Linux 构建替代。

## 交付安排

用户已于本轮明确要求：完成后提交到远端。继续按功能批次本地提交，全部适用任务及门禁完成后推送远端分支；不纳入历史原始采集、临时制品和无关工作树改动。当前未推送，不宣称远端 CI 或主线合并已完成。

用户要求加快进度、减少反复测试：后续按相关功能批次定向调试，批次末统一完成必要回归；通过后仅因新改动、失败或未解决风险复跑对应检查，避免反复执行无关全量测试。安全负向和真实业务验收保留。

[D2h 实际 OpenShell 镜像与双向通道](optimization-opt08-image-profile-validation-20261007.md)已完成：43 项通道、11 项镜像边界、11 项真实 OpenShell 组件检查和 21 项旧只读 bind profile 回归通过。运行进程核验 root 保护文件和明确的 PID namespace 双向凭据，拒绝容器内伪造服务端；未修改日常网关、原镜像或业务挂载合同。首次构建兼容性问题修复后，独有沙箱和网络清理成功。本批没有重跑无关 Go/前端全量；实际 Hermes 任务、在线 Authority 和两个业务 Skill 的同次运行仍待接通，OPT-08 与 9/16 状态保持。

[D2i 同次真实运行联验](optimization-opt08-joined-runtime-validation-20261007.md)已接通实际 OpenShell 沙箱、Hermes 原生工具、宿主转发、Go HTTP Authority 与真实签名安装来源。8 项检查/8 条签名回执通过：reader 读允许、写拒绝；切换 writer 后仍受两层权限交集限制；独立 writer 合法写成功、越界写拒绝，宿主独立核对文件效果。修复租约截止漂移和原生受保护 Skill 加载分类；Python 30 项、Go 受影响五包完整测试/三包定向 race、vet 和四目标构建通过。两个 Skill 内容与操作员为合成测试材料，尚未验收模型对话/日常业务入口及其余场景，OPT-08 保持 implementing，总计仍为 9/16（56.25%）。

[D2j 并发与撤权联验](optimization-opt08-lifecycle-validation-20261007.md)已在同一实际 OpenShell/Hermes/Go 链路通过 18 项检查：新增同进程并发任务权限隔离、调用重放拒绝、结束后拒绝及 SEC、Skill Grant、Agent 基线三种撤权。23 次工具尝试形成 18 条签名回执（14 allow、4 deny），另 5 次在决策前拒绝，不伪称 deny 回执。宿主独立核对允许文件与拒绝目标；真实集成测试、Ruff、server vet 通过，仅扩充验收夹具，未重复无关全量。测试操作员与 Skill 内容仍为合成材料；业务入口/业务权限撤销、网络、过期/升级/漂移及审批重试尚未完成，任务状态与 9/16 完成数不变。

[D3a 管理 HTTP 接入](optimization-opt08-management-enrollment-validation-20261007.md)已限定开放创建 v3：显式 native-host 服务完整绑定且私有连接有效，管理鉴权、批准基线和 revision 约束保持，读回始终 unverified。真实 OpenShell 18 项检查已改用 HTTP 配对/身份签发/会话登记通过；Go 全量 45 包、server 定向 race、全量 vet、四目标构建及 16 项 Python 合同通过。此增量替代上述 D2“创建入口关闭”的阶段状态；受保护日常启动与业务验收仍未完成，OPT-08 与总体 9/16 保持不变。

[D3b 受保护运行初始化](optimization-opt08-runtime-bootstrap-validation-20261007.md)已提供 ImageBootstrap 并纳入固定覆盖包：一次性配置、排他私有目录、固定跨 PID namespace 响应凭据及目录/端点变化、fork、超时和关闭后的拒绝。新增 39 项启动测试、相关共 138 项 Python 测试通过；实际 OpenShell 使用该初始化器及其制品摘要，18 项权限检查通过。未改 Go 生产逻辑，未重复无关全量。初始化器尚未接入日常网关与业务 API，业务核心文件的既有修改继续保留；OPT-08 与 9/16 不变。

[D3c 请求级子身份衔接](optimization-opt08-request-identity-validation-20261007.md)修复原生 namespace 无法兼容业务请求前缀的问题：两入口共用严格 ASCII 冒号组件校验，派生会话不超过 256 字节。真实 HTTP 签发子身份、错范围登记拒绝、子凭据 OpenShell 联验 18 项通过，包含父基线撤销后拒绝；163 项相关 Python、Go 身份定向与 server vet 通过。请求参数和 Skill 内容仍为合成，日常业务 API/授权生命周期尚未验收，OPT-08 与 9/16 不变。

[D3d 固定网关入口](optimization-opt08-gateway-entry-validation-20261007.md)在同一 PID 初始化后进入已有 gateway.run.main，拒绝旧插件环境和任意额外参数；62 项相关 Python、固定镜像真实网关启动 8 项与原生函数 21 项通过。网关启动 socket 为合成协调设施，无模型/在线裁决，不能替代真实业务验收。业务身份客户端、原生宿主监管及日常 API 接线继续实施，OPT-08 与 9/16 不变。

[D3e 业务原生身份客户端](optimization-opt08-business-identity-validation-20261007.md)在业务独立分支新增严格 HTTP 消费者，49 项定向通过；真实 Go HTTP 首次签发/登记/取消与取消后拒绝、运行身份幂等读回及父基线撤销后的精确取消均通过，同次 OpenShell 18 项检查通过。业务提交只含四个新增文件，既有改动保留。日常 builder/Supervisor 与业务授权/模型闭环继续接入，OPT-08 与 9/16 不变。

[D3f 宿主持续服务循环](optimization-opt08-host-loop-validation-20261007.md)已区分正常空闲与连接失败，在固定租约内服务，停止/过期/guard 失效后拒绝转交允许结果；fork 后控制和失败后重启拒绝。88 项相关 Python 通过，最终循环 15 项通过（新增 2 项），Ruff 通过；实际 OpenShell 18 项权限检查、18 条签名回执、宿主效果及线程/沙箱清理通过。业务身份客户端 HTTP 联验保持通过，日常 builder/Supervisor 与模型闭环尚未验收，OPT-08 与 9/16 不变。

[D3g OpenShell 后端归属核验](optimization-opt08-openshell-backend-validation-20261007.md)已从验收脚本提取为正式宿主组件，固定本机 Docker 端点、完整容器/镜像/OpenShell 归属和真实进程清单、cgroup/NSpid，异常永久拒绝。最终后端 53 项通过，相关阶段 63 项通过（重叠）；真实 OpenShell 18 项检查、18 条签名回执及清理通过。已修复非 root 读取 root init namespace 的不合理前提，并减少夹具重复健康轮询、调整整批等待上限，保留三轮失败记录；逐请求期限不变。日常 Supervisor 跨进程交接与模型业务仍未验收，OPT-08 与 9/16 不变。

[D3h 业务监管与宿主会话](optimization-opt08-host-session-validation-20261007.md)已统一真实后端/guard、监管者 pidfd、固定期限/90秒内心跳、Verifier 和循环生命周期；过期/退出/停止后拒绝，线程退出未确认时保留在用资源。最终相关91项通过；真实OpenShell18项检查、18条签名回执、4次合成业务续期及会话/沙箱清理通过。另修复线程创建失败后的清理异常，由增量负向验证；live旧宿主模块与最终源码摘要分列。跨进程认证控制、日常API及模型业务仍未验收，OPT-08与9/16不变。

[D3i 跨进程宿主控制](optimization-opt08-host-control-validation-20261007.md)已实现私有认证控制服务及业务独立客户端：监管者 PID 取自内核凭据，控制材料固定、句柄不可复活，处理器与资源有界。53项相关测试、额外2项配额负向及业务21项通过；真实OpenShell由独立业务消费者启动/4次续期/停止，18项权限检查、18条签名回执和清理通过。业务四个新增文件独立提交，未吸收既有工作树修改。独立CLI只验收启动/停止，日常builder/Supervisor/API/模型尚未验收；OPT-08与9/16保持不变。

[D3j 业务Supervisor原生接线](evidence/optimization-20261007/native-business-supervisor.json)已落盘显式v6、RequestNative和准备/运行态区分，真实监管方法先复查业务授权再控制宿主；关闭失败继续containment且不报完整成功。相关135项通过，最终原生专项21项通过（重叠14项，新增7项），Ruff通过。组件使用明确授权/宿主/资源夹具，日常builder/受保护网关/endpoint和模型业务尚未验收。业务必要导入闭包存在27个未跟踪模块，已保留改前快照、盘点并暂不提交依赖不完整的本批业务源码；后续审查必要依赖一并交付，不纳入无关修改。OPT-08与9/16保持。

[D3k 原生配置与快照](evidence/optimization-20261007/native-runtime-config.json)已补齐显式原生编译、v4 fresh快照、挂载校验与旧入口拒绝；原生16项通过。相关74项通过、1项因既有Qwen路由候选摘要漂移失败；经10项实际模型/制品静态核验后修正绑定，该项复跑及路由13项通过。审计保留外部晋级门禁，不宣称模型业务就绪；未重启模型、无推理调用。受保护镜像/builder/网关/endpoint仍待接线，业务增量保留本地待依赖审查，OPT-08与9/16不变。

[D3l 受保护业务镜像与启动交接](evidence/optimization-20261007/native-request-image.json)已构建独立原生候选：实际镜像5项、真实Hermes启动交接9项通过，包括宿主接管前HTTP关闭、重复启动拒绝及子进程/容器清理。首轮专项41项、最终镜像专项26项（新增10）、相关旧运行配置/快照/挂载73项通过。业务自包含bootstrap/测试及合同报告已提交，其余原生接线仍待必要依赖审查；没有Authority接管或模型调用，日常服务未替换。builder/assets/网关/endpoint和真实业务验收继续，OPT-08与9/16不变。

[D3m 原生请求规划与资产](evidence/optimization-20261007/native-request-assets.json)已接入显式镜像选择、计划/资产v2、配置摘要绑定、无旧relay的原生策略及恢复版本分离。原有相关86项、新部署/策略10项、完整恢复41项、启动恢复与最终原生资产36项通过（含首轮14项及新增1项）。保留API解释器和安装来源校验，修复测试工具环境收集问题。核对确认旧mount计划本就无配置bind，纠正D3l推测；未启动沙箱/模型。身份签发、监管启动、网关PID/endpoint与真实业务仍待接通，业务源待必要依赖审查，OPT-08与9/16不变。

[D3n 原生业务入口接线](evidence/optimization-20261007/native-request-wiring.json)已连通签发、v6监管、无旧relay的forward、实际宿主PID定位、固定镜像网关、v2端点与原claim builder/私有配置selector。相关签发监管恢复53项、进程/旧forward32项、旧业务链路111项、新旧selector62项、最终原生专项63项通过（分批重叠，不累加）。旧安装包缺少access_scope与新venv硬链接问题在隔离测试环境解决，保留来源校验，未修改日常API环境。自包含进程观察器/测试及合同报告提交业务4a25b38；其余业务增量待必要依赖审查。实际批准业务Skill镜像、私有部署目录及真实模型业务/生命周期尚未验收，OPT-08和9/16保持。

[D3o 业务Skill镜像与实际安装](evidence/optimization-20261007/native-business-skills.json)已加入两项真实业务Skill、固定清单导出、原生配置v2与受保护镜像v2；最终72项定向和17项相关API回归通过。实际镜像6项、启动交接9项检查通过，真实Hermes发现两项业务Skill，同时如实记录skill_manage可见但未获授权。实际serve --native-host/独立宿主通过公开管理API完成两项批准安装、独立Agent基线和制品绑定，8项检查通过；重启同一状态后业务客户端签发/登记/取消子身份，未登记运行拒绝，8项检查通过。未调用模型，未验证真实读写效果；私有状态保留、日常环境未修改。业务依赖闭包与真实业务生命周期仍待完成，9/16不变。

[D3p 真实业务API首批权限验收](optimization-opt08-business-api-validation-20261007.md)已通过DGX Spark、本地Qwen、Hermes原生Skill、OpenShell与SIQ的真实业务HTTP链路：v811公司元数据读取允许且答案匹配；v812只读Skill写入被明确拒绝、文件未创建；v813独立写入Skill获准且正文正确。8条完整回执经公钥独立验签与链序核对。修复启动器/来源读取器多余的祖先目录读取权限要求及原生HTTP就绪时序；安全侧115项、业务启动15项/端点43项定向通过。v810财务证据门禁阻断及v812/v813测评器资源比对勘误保留，未关闭业务门禁、未重复模型调用伪造通过。实际API自有包更新和两处父目录权限收紧已有备份；临时数据库、候选网关/模型桥清理完毕，原模型未重启。同请求切换等完整生命周期、业务依赖闭包及最终交付仍待完成，OPT-08与9/16保持。

[D3q 业务交付依赖](evidence/optimization-20261007/native-business-delivery-review.json)扩大静态盘点至原生业务选择器／网关、镜像和编译器，共109模块、提交前66个未跟踪模块；先审查提交配置校验依赖，四文件隔离目录27项通过、Ruff通过。业务提交547a274，完整依赖与动态部署资产尚待交付。

[D3r 同请求Skill切换](optimization-opt08-switch-validation-20261007.md)通过真实业务请求v814：先加载只读Skill，再加载写入Skill，实际写入仍被SIQ拒绝；签名回执保留准确两个Grant和原只读上下文，目标文件不存在。新增三条回执与原八条组成11条链，公钥独立验证通过，旧记录未改。原测评器及独立复核均通过；临时数据库／请求资源／候选网关／模型桥清理，原模型服务未变。并发、撤权、漂移等其他生命周期未完成，OPT-08与9/16保持。

[D3s 原生上下文管理](optimization-opt08-context-management-validation-20261007.md)补齐管理员专用v2历史读取、分页和精确撤权HTTP接口，合同与实现分别提交；运行宿主失联不阻止管理员撤权。Go全量45包、两包相关race、vet、26项Python合同和四目标构建通过，查询控制字符缺口已修复。新Authority安装及重启各8项通过。真实业务v815正常写入与v816读取后HTTP撤权对照均通过；后者实际写入报错且目标不存在，在决策前拒绝、没有伪造deny回执。独立复核18项、五条完整回执链和SEC／撤销签名通过；请求资源清理、原模型不变。现有v1页面未接入v2管理。OPT-08与9/16保持。

[D3t 请求范围与启动依赖交付](evidence/optimization-20261007/native-business-delivery-scope-review.json)审查并提交业务六个源码／测试文件（业务b642164）：输出路径、企业数据范围和兼容启动握手。修复畸形范围输入未处理TypeError；独立六文件目录51项、Ruff和既有范围／签名broker消费者22项通过。原109模块静态闭包中仍有61个未跟踪模块，动态资产／迁移另计；不宣称全业务可复现交付。此输入错误处理修复发生在v815/v816之后，历史测评候选身份不改写。OPT-08与9/16保持。

[D3u 原生业务授权撤销](optimization-opt08-business-revocation-validation-20261007.md)在v817发现业务Grant撤销后仍只按旧身份引用执行隔离，无法确认原生v6请求；失败和随后清理分别保留。补齐原生精确取消分支，相关91项、最终撤权21项（重叠）及Ruff通过。真实v818已通过：业务撤权HTTP200、继续读取403、流报告授权丢失且无成功done、旧子凭据401／子身份revoked、父身份active、请求及沙箱／监管／转发回收；25.309秒为单次终态清理时长，不是撤权时延SLA。独立18项及含两次运行的九条完整回执链通过。业务实现／测试仍待必要依赖审查提交，已记录源码摘要；OPT-08与9/16保持。

[D3v 运行依赖交付与模型桥来源修复](optimization-opt08-runtime-delivery-validation-20261008.md)完成必要身份兼容、受控模型路由／候选审计、认证模型桥三批业务提交（7c410f6、98fd1cc、7eecae8），独立目录分别98／34／82项通过，Ruff通过；另有当前工作树路由消费者13项通过。修复NaN参数及overflow UID误当root问题，模型桥显式绑定已批准Docker字节并通过匿名私有快照执行。实际受限systemd三项检查、真实桥启动／401／精确停止通过；memfd执行受限失败保留，系统保护未放宽，模型PID／InvocationID／重启次数不变。原109模块闭包仍54个未跟踪，动态资产另计；完整交付和最终候选业务回归继续，OPT-08与9/16保持。

[D3w–D3y 生命周期依赖交付](optimization-opt08-lifecycle-delivery-validation-20261008.md)提交网关／资源输入、数据身份／准入／租约、独占占用／停止保护三批业务依赖（d40ad53、f50d3b6、f2e8006），隔离38／62／26项与Ruff通过；当前工作树消费者1／121项另计。修复资源选项重复覆盖、畸形租约phase跳过撤权和异常身份／owner类型；原反例保留，旧令牌在修复后被拒。固定上游重放两份挂载补丁，Rust目标摘要与既有候选合同一致，未新增Rust构建或实际沙箱测评。真实模型／权限／服务未变；原109模块仍42个未跟踪，完整业务交付和最终候选验收继续，OPT-08与9/16不变。


[业务配置、数据授权与策略依赖交付](optimization-opt08-config-policy-delivery-validation-20261008.md)：业务配置／数据授权／策略四批交付e8a4acd/2d96fe8/50c1b83/0fd5d5a；隔离35通过1跳过、81通过、76通过、181通过，Ruff通过，最终加强CLI负向单项通过（重叠）。修复出网分类畸形字段TypeError和负向测试提前失败假通过；补齐公开profile资产并交付原未满足的policy消费者。依赖均取已提交版本，最终文件摘要与提交核对；未调用模型或改动真实服务。原109模块仍39个未跟踪，完整交付／最终同候选验收继续，OPT-08与9/16不变。


[原生镜像与relay兼容依赖交付](optimization-opt08-image-relay-delivery-validation-20261008.md)：原生镜像与relay兼容依赖交付业务bae0a50/4ac075a，隔离88/22项与Ruff通过；隔离源码实际复核既有业务镜像六项保护检查和四份资产摘要，通过且无模型调用。修复离线检查空集合误通过、relay描述符冲突及check-only虚报非特权。原109模块仍36个未跟踪；基镜像资产、API/监管完整交付与最终候选验收继续，OPT-08与9/16保持。

[API授权与迁移交付](optimization-opt08-api-authority-delivery-validation-20261008.md)：业务API授权／执行租约及连续迁移依赖交付5be2a77/c8ee0df，隔离迁移24项、API64项及Ruff通过。修复ORM缓存导致账户／grant／执行租约旧状态被复用，以及快照到期瞬间误接受，11项旧负向已复现。真实临时PostgreSQL验证迁移回放与审计失败回滚，容器已清理；未访问日常业务库或模型。主链交付至021，工作区022–024保留；Supervisor集成完整用例留待后批。原109模块仍34个未跟踪，完整交付及最终同候选验收继续，OPT-08与9/16不变。

[监管与转发依赖交付](optimization-opt08-supervisor-delivery-validation-20261008.md)：监管／原生身份／受管转发六模块、两服务模板和五测试文件交付业务6a4e8b6，隔离49文件155项与Ruff通过；先前保留的API租约接管集成用例完整交付。fork／锁／信号为真实本地组件，systemd、Authority和业务资源切断仍为夹具，未安装服务或调用模型。原109模块剩28个未跟踪；候选镜像15份动态输入摘要一致但交付审查未完成。完整编排／撤权／同候选业务验收继续，OPT-08与9/16不变。

[候选镜像与业务工具资产交付](optimization-opt08-candidate-assets-delivery-validation-20261008.md)：候选镜像／MCP／报告资产交付业务f2bdc8b，105文件隔离验证109项及Ruff通过；两补丁实际回放和九wheel来源／许可核对通过。查明旧镜像只有配置校验器来源不同，代回旧摘要可完整复算旧构建身份；当前源码离线构建新镜像56c3d4d6ad39，七项运行检查及42个输入摘要通过。保留旧快照／镜像／证据，不激活服务、不调用模型；夹具发布不冒充生产审批。原109模块剩26个未交付，完整编排与最终新鲜候选验收继续，OPT-08与9/16不变。

[请求编排组件预审](evidence/optimization-20261007/native-request-orchestration-prereview.json)：请求编排组件预审：独立226文件、61份选定源码／测试，486项通过、Ruff通过。使用HEAD离线构建并核验的控制包，补齐HEAD动态资源；未修改日常API环境。代码尚未提交，聊天API入口及相关完整集成用例仍待交付审查；不能把组件预审视为OPT-08或同候选业务验收。9/16保持。

[请求编排与业务 API 依赖交付](optimization-opt08-request-api-delivery-validation-20261008.md)：请求编排与业务API完整依赖交付业务2a70587：110份选定输入的最终隔离API回归523项通过；修复原生请求因缺旧canary字段而漏导出安全生命周期事件，旧反例复现、相关45项通过（与523重叠）。Ruff基线104条、本批102条既有B008、新增0。保留报告归档等无关工作区改动及初始失败；未启动真实业务或调用模型。最终新鲜候选／生命周期／四臂验收继续，OPT-08与9/16保持。

[原生真实业务三例复核](optimization-opt08-working-business-validation-20261008.md)：原生真实业务v819–v821：合法读取、只读Skill实际拒写、写入Skill实际可写均通过；6条回执独立验签／链验证及v3 schema通过，文件效果对应。两个写入用例Agent基线相同、OpenShell可写挂载与归一化文件系统策略相同，SIQ按Skill Grant区别裁决。干净源码映射遇systemd 226/NAMESPACE；实测采用冻结工作区1873输入（289项与HEAD不同），前后字节一致，不能冒充干净提交验收。自有资源回收、原模型未重启；每例一次，重复／生命周期／四臂与完整交付继续，9/16保持。

[真实权限三次重复与公开核验](optimization-opt08-opt10-repetitions-validation-20261008.md)：冻结工作候选v819–v827完成读取、只读拒写、授权可写各三次独立业务请求；18条回执和9份SEC独立验签、schema及文件效果核对通过，源码清单／已安装运行包保持一致。新增公开离线核验器，5项真实证据／篡改／跨请求替换／重复计数检查及Ruff通过。OPT-10进入implementing；289项未提交输入、干净部署、剩余生命周期／四臂与平台验收仍待完成，总体9/16保持。

[安装内容漂移真实对照](optimization-opt08-install-drift-validation-20261008.md)：安装内容漂移真实对照v828/v829通过：同一获批写入Skill正常读写成功；读取后受控修改宿主安装SKILL.md内容，后续实际write_file报错、目标不存在，无伪造deny回执。原字节／inode／硬链接关系恢复，源码与模型不变，自有资源清理；新增5条回执，与原18条组成23条链，11份SEC公钥／schema核验通过。仅一组安装源漂移对照，其他生命周期／四臂与干净交付继续，9/16保持。

[同请求Skill切换三次重复](optimization-opt08-switch-repetitions-validation-20261008.md)：同工作候选v830–v832完成三次同请求Skill切换：两次原生加载均允许，实际write_file均因grant_scope_violation拒绝、目标不存在；两个Grant和签名父上下文保留，OpenShell任务目录可写。新增9条回执／6份SEC，完整32条链／17份SEC独立验签、父子绑定与schema通过；公开核验工具5项相关回归及Ruff通过。原模型、业务源码不变，自有资源清理。该组不是并发隔离，干净交付／其余生命周期／四臂／平台验收继续，9/16保持。

[企业OpenShell行为协议与校验器](optimization-opt09-protocol-validation-20261008.md)：ADR-058及企业OpenShell单次挑战／v2观测合同、纯校验器完成；58项新用例和63项v1回归共121项通过，Ruff通过。覆盖时效／nonce／范围／前后策略与保护身份／三臂和前后可达性约束。全部为合成组件证据；纯校验器不承担持久CAS或认证，生产部署仍只做配置读回。持久协调／真实ELF收集器／API前端接线和真实三臂验收继续，总体9/16保持。

[企业OpenShell行为持久台账](optimization-opt09-journal-validation-20261008.md)：企业行为验证持久台账、单向状态／CAS、一次领取／消费、父操作来源核对与0031迁移完成。定向166项及最终台账32项通过（重叠），真实临时PostgreSQL40项通过，含两组实际行锁竞争、六状态审计回滚及非空降级保留。领取前观测误接受已复现并修复；Ruff通过。全部观测仍为合成材料，真实ELF收集器、API／授权／目标互斥及前端接线和真实三臂验收继续；生产等级未提升，总体9/16保持。

[企业OpenShell静态ELF与观测通道](optimization-opt09-elf-channel-validation-20261008.md)：静态Go ELF、agent v1观测合同与有界回显通道完成；真实本机TCP／ELF和协议兼容共160项通过（39新＋58协议＋63历史），Ruff／Go vet／gofmt通过。无策略拦截的三轮12次连接全部成功时，校验器明确拒绝防护有效结论；错误回显、EOF、超时、reset、拒绝和伪造报告均分列。没有真实OpenShell调用，自报身份不替代独立保护核验；目标保护观察器、企业协调API／前端和真实三臂继续，总体9/16保持。

[独立程序保护与首次真实OpenShell探测](optimization-opt09-protection-validation-20261008.md)：独立Docker保护观察器、v1保护事实及ELF低权限检查完成：84项保护／通道、最终46项保护（重叠）及12项真实Docker检查通过；Ruff／Go vet通过。真实OpenShell三次尝试保留：启动capability模板与镜像UID998已修正，003实际保护通过但原始TCP允许／拒绝各三次均refused、六次主机对照成功，校验器正确不予采信。全部自有网关／沙箱／网络清理，原模板及TLS不变；需新增显式代理通道协议并完成真实差分、协调API／前端，OPT-09与9/16保持。

[显式CONNECT与真实OpenShell差分](optimization-opt09-connect-validation-20261008.md)：显式CONNECT挑战v2／结果v3／agent v2及持久台账兼容完成，相关172个不同用例分批通过（初次schema引用失败修复，重叠不累加）；新ELF真实Docker保护12项通过。真实独立OpenShell同目标三轮允许3/3、明确policy_denied拒绝3/3、主机前后对照6/6，接收端9条标识；原拒绝路径显式授权后新挑战连通、再收到1条，旧策略证据失效。9项真实检查及清理通过，公开观测离线核验通过。生产认证协调／目标互斥／可信代理模板／API前端及等级生命周期仍待接线；合成operation绑定不冒充生产端到端，OPT-09与总体9/16保持。

[操作员模板与同次持久协调](optimization-opt09-coordinator-validation-20261008.md)：操作员批准模板与内部持久协调器完成：模板文件／祖先权限及完整目标绑定、每臂授权复核、共享目标互斥、提交后联网、完成事务授权与二次期限检查。57项定向通过；真实专用OpenShell的持久策略下发、同次持久行为收集、重复不重放、数据库绑定撤权、三轮差分及清理共12项通过，独立查询确认唯一accepted/epoch2及三条审计、父操作revision/digest吻合。真实运行使用隔离SQLite与合成审批身份，生产认证API／目标授权链／前端及等级生命周期尚待接线；未提升部署等级，OPT-09与9/16保持。

[企业认证行为API与真实OpenShell接线](optimization-opt09-api-validation-20261008.md)：认证行为API、批准模板持久绑定及0032迁移完成：167项定向回归、真实临时PostgreSQL43项通过；专用OpenShell12项及同次认证API6项检查通过（有重叠）。实际RS256认证、三臂探测、重复不重放、撤权拒绝与三条主体审计完成；独立读库／协议／schema复核通过。身份发行者及审批为合成材料，数据库为开发SQLite、请求经ASGI；不冒充生产IdP／PostgreSQL同次端到端。原配置不变，自有资源清理；前端及等级生命周期仍待接线，OPT-09与9/16保持。

[企业OpenShell行为闭环验收](optimization-opt09-completion-validation-20261008.md)：企业OpenShell行为证据闭环适用范围验收完成：批准模板预览与v2摘要绑定、accepted态独立核验、当前限定等级／审计、前端时效及不重放恢复已接线。后端154项、前端31项、PostgreSQL48项通过；同次真实OpenShell13项／API9项及实际浏览器HTTP核验通过，故障浏览器9项另计且不混淆。实际策略变更使等级转unverified，历史accepted不改写；自有资源清理。生产IdP、持续监控和未覆盖路径不作通过声明，其他任务与最终交付继续。OPT-09记done，总体10/16（62.5%）。

[钩子安装归属与漂移诊断第一批](optimization-opt12-integrity-validation-20261008.md)：安装归属／漂移诊断首批完成：修复已安装钩子全删误报未安装、密封材料损坏仍显示就绪及明文伪造卸载绕过计划认证。Go全量1736顶层通过／34跳过，最终完整性7项与新增管理接口1项、合同3项通过；vet、Ruff、受控源码格式与四目标构建通过。组件诊断不冒充原生宿主强制阻断；完整发行身份、受保护加载和实际执行后果继续，OPT-12为implementing，总体10/16保持。

[受保护钩子与执行拒绝联验](optimization-opt12-protected-hook-validation-20261008.md)：受保护钩子实效联验完成：独立OpenShell＋当前Hermes原生工具＋真实Go Authority下，两个正常写入成功，钩子／清单六次改写删除替换均拒绝；管理员注入代码漂移后实际写入被拒且无副作用，恢复字节不复活旧guard。002完整18项检查通过，50项组件和9项证据回归通过；001清理复验异常保留且资源已清理。仅合成批准Skill、无模型，非日常业务／正式发行验收；OPT-12继续implementing，总体10/16保持。

[安装程序身份与升级恢复](optimization-opt12-program-identity-validation-20261008.md)：安装程序身份读回完成：复用密封计划的准确路径和BinaryDigest，发现程序改写／删除／异路径；旧计划无摘要为unknown，明确升级后认可新身份，中断恢复重新核对旧身份。五个旧反例复现；Go全量1741顶层通过／34跳过，定向45项与合同4项、vet/Ruff/格式/四目标构建通过。当前验证器另复核历史0.4.0真实签名包及四类篡改拒绝，不能冒充当前候选签发或原生验收；OPT-12继续implementing，总体10/16保持。

[独立静态扫描服务与容器验收](optimization-opt14-host-service-validation-20261008.md)：新增 UID 认证 Unix 通道与独立宿主 bwrap 服务，保留 Docker 默认 AppArmor/seccomp、非 root 和只读根目录；真实正常/恶意扫描、资源失败恢复、错误 UID/权限漂移拒绝、失联失败关闭与重启恢复通过。相关187项、最终专项35项（33重叠，独立合计189）及 Ruff/镜像锁/Compose 配置检查通过。修复 COPY 保留0600源码导致容器启动失败，001/002失败保留，003完整13项组合检查和资源清理通过。开发身份/SQLite不冒充生产IdP验收，未安装常驻服务或推送；OPT-14记done，总体11/16（68.75%）。

[企业安装/升级候选准备](optimization-opt11-release-preparation-20261008.md)：固定a9a8e91e的285个已提交企业源码输入，构建两个预发布版本、各8个Linux双架构制品和候选外独立验证器；16个制品/ZIP摘要、6次原生describe、两次显式开发目录扫描、未签名/伪造签名拒绝、安装前停止与组包无输出均通过。独立源码首轮9项因缺测试专用输入失败，补同提交5个文件后定向9项通过；最终220顶层通过/2条件跳过（含子测试689通过）。未读私钥、未签发/安装/升级，正式签名材料与真实设备迁移/服务升级仍待验收，OPT-11及总体11/16保持。

[企业升级前核验与确认绑定](optimization-opt11-upgrade-review-validation-20261008.md)：新增只读review-enterprise-upgrade，绑定现有设备私密状态、旧/新签名暂存、完整采集计划和服务配置；身份/范围/权限/链接/漂移/过期与取消拒绝，中文规范化摘要跨语言一致。Go全量226顶层通过/2条件跳过（720含子测试事件），定向race6顶层、Python合同11项、vet/格式/Ruff与四目标构建通过；实际ARM64 CLI拒绝伪造发行且文件不变。成功review为验签替身组件证据，非正式签名正向；切换事务、持久恢复及真实服务升级继续，OPT-11和总体11/16保持。

[OPT-11 升级持久记录与运行阻断](optimization-opt11-upgrade-journal-validation-20261008.md)已完成组件实现：排他持久 pending、原始/目标/恢复状态摘要绑定、严格只读恢复核验、普通任务阻断、先锁后读及祖先目录核验。首轮全量有两份旧夹具权限失败，修正自有夹具后定向 race 通过；本批去重累计 238 个顶层 / 784 个含子测试通过，2 条既有条件跳过。26 项 Python 合同、升级/任务锁 race、vet、Ruff、四目标构建及真实 Linux CLI 10 项启动阻断检查通过。尚无配置切换/恢复公开命令或正式签名升级验收，旧周期确认须按既有流程退出，不能自动扩展授权。OPT-11 保持 implementing，总体仍为 11/16（68.75%）；未推送。

[OPT-11 显式升级切换与恢复](optimization-opt11-upgrade-apply-validation-20261008.md)已接入公开命令：停服条件严格核验、签名来源程序固定 FD 探测恢复协议、state/unit 持久切换、daemon-reload、完成归档及明确方向恢复，均不自动启动或授予业务权限。最终全量 251 顶层/820 含子测试通过，2 条既有跳过；包括独立进程在配置持久化后直接退出再恢复与协议字段精确匹配，相关 race 通过。38 合同、相关 race/vet/Ruff、四目标构建和真实 Linux CLI 10 项检查通过。组件正向验签与服务管理器为明确替身，正式签名包与真实服务/迁移验收仍待完成；替代前批“尚无切换/恢复 CLI”的阶段状态，OPT-11 和总体 11/16（68.75%）保持不变。

[OPT-11 新升级候选准备](optimization-opt11-upgrade-candidates-20261008.md)：从 `63a8cfc0` 固定 297 个 Git 输入，生成未签名 .3/.4 候选及候选外独立验证器。原生协议/版本读回、16 个 ELF 与 ZIP 内容、6 次 describe、2 次开发扫描、固定验证器及 setup/finalize 拒绝通过；干净导出 31 顶层/131 含子测试升级回归通过，导出身份不变。旧 .1/.2 无新恢复入口已实测并保留。尚缺受控签发与真实服务/迁移验收，业务干净部署仅作只读定位，OPT-11 与总体 11/16（68.75%）不变。

[OPT-08/10 干净候选 API 与授权验证](optimization-opt08-clean-api-validation-20261008.md)：业务f73e566统一请求所有权状态路径，保留缺失/权限/损坏拒绝。242项相关回归通过；14项新检查在干净导出独立复验通过（重叠子集）。新venv复制安装同提交4个自有wheel后，真实HTTP授权/幂等/撤销及恢复就绪11项检查通过，关闭时1483模块条目无工作区源码导入，15个自有包模块绑定对应13个文件字节匹配。临时资源清理、日常服务不变；保留初始未就绪、旧包来源差异、非受信安装目录与硬链接拒绝。未调用模型，原生Skill完整业务/四臂/平台验收继续，OPT-08/10与总体11/16保持。

[OPT-08/10 真实业务撤权与重复验证](optimization-opt08-business-revoke-validation-20261008.md)：真实业务撤权v834试点通过：当前SEC Git导出二进制与登记1874输入/289补丁的f73e566业务工作候选，原生Skill加载/读取后撤销业务授权，活动查询403、SSE失权无done、子凭据401、父身份有效、约25.287秒终态及资源回收。2回执/1 SEC独立验签schema通过。v835重复启动失败且已回收，v836按规则未执行；不宣称三次通过或撤权后实际写入拒绝。业务74d9024新增固定允许列表端点诊断，26项定向通过，仅诊断改进不是启动修复。遵循OPT-10分别登记跨仓补丁，不把完整业务仓路径重构另作前提；完整矩阵和最终全栈冻结仍必需。OPT-08/10与11/16保持。

诊断候选74d9024的v837真实撤权复测通过，约38.375秒终态；相同1874输入范围重新冻结，候选摘要52596e44。新增2回执/1 SEC，累计4回执/2 SEC独立验签及schema通过；原服务配置恢复、模型不变。v835启动失败没有复现，仍未解决，不能合并为同候选三连通过。两轮撤权后监管单元保留failed/exit-code状态但进程PID0，资源回收与服务退出状态分开记录；后续继续启动可靠性、撤权后工具尝试和其余矩阵。总体仍为11/16（68.75%）。

[OPT-08/10 原生终止确认修复与复测](optimization-opt08-terminal-cleanup-validation-20261008.md)：业务7e52689为原进程/原handle的stop增加有界终止确认重试，不重试start/renew、不放宽身份校验。旧实现2项反例失败，相关86项及Ruff通过。v838–v841四次真实启动/取消通过但v835启动失败未复现、未解决。修复候选v842–v844三次真实模型输出后业务撤权通过，约32.879/30.811/24.314秒终态；不再出现close_native或containment_failed，撤权触发failed_closed仍保留systemd failed/退出1、PID0。新增6回执/3 SEC，完整10回执/5 SEC及3个请求绑定独立核验通过。v843/v844各有首次读取报错后重试成功，未认定为防御成绩。后两轮API依赖11663文件/4链接前后不变，非全栈冻结。原模型/配置恢复、自有资源清理。撤权后工具尝试、启动/读取错误归因、其余矩阵/平台/签名交付继续；11/16不变。

[OPT-08/10 崩溃恢复与排队到期](optimization-opt08-crash-expiry-validation-20261008.md)：同业务候选7e52689新增v845真实Skill读取/模型输出后API SIGKILL与原数据库重启试点，原租约自然失效且未接管/续租，约126.976秒转authority_lost、子凭据401、最终资源回收；首次containment_failed后ExecStopPost recover通过，failed/退出1状态保留。v846真实排队Grant自然到期约59.404秒后受控503、pending released、无沙箱/模型/新增回执，合成占位保持且由所有者释放。新增2回执/1 SEC，完整12回执/6 SEC及新请求绑定独立核验；源码/驱动/pending/终态复核通过，11663依赖文件/4链接前后不变。每例仅1次试点，数据库断言源于现场固定驱动，非事后重查；运行中SEC到期、恢复后新任务、其余矩阵/平台/签名交付继续，11/16保持。

[OPT-08/10 模型访问回收修复](optimization-opt08-containment-repair-validation-20261008.md)：业务8851724修复在途模型流占锁导致的首次清理失败：仅明确admission锁超时且沙箱删除/空清单已确认时，对原运行模型凭据轮换追加一次重试，其余失败保持失败。75项不同相关检查通过；诊断v847复现model_access失败且锁由自有桥持有，修复v848真实API崩溃复测记录busy→recovered、监管退出0/PID0、业务authority_lost及资源清理通过。约139.098秒恢复等待不是低延迟SLA。两候选分别登记，独立新Authority链4回执/2 SEC/2请求绑定验签通过；依赖11663文件/4链接前后不变，非全栈冻结。其余生命周期/四臂/平台/正式签名继续，11/16保持。

[OPT-08/10 恢复后新任务实证](optimization-opt08-post-recovery-validation-20261008.md)：同修复候选8851724完成v850真实API崩溃自然恢复后新合法请求：43项现场检查通过，同API/数据库/会话的新run加载Skill、读取并完成模型输出；旧终态摘要不变、旧子凭据仍401，新请求最终释放，两监管服务退出0/PID0，源码/配置/原模型保持。恢复等待110.850秒；模型生成耗时另计，新任务首次read_file报错后重试成功，原因未定。v849因把按会话复用的活动租约槽误当历史表而失败，按合同修正驱动并保留失败，不修改产品或补记通过；隔离组件3个不变量核对通过。新增4回执/2 SEC，含v849等既有记录共12回执/6 SEC和本轮2请求绑定独立验签；依赖11663文件/4链接前后不变。剩余生命周期/四臂/平台/签名交付继续，11/16保持。

[OPT-08/10 Skill 撤权后的工具与文件效果](optimization-opt08-skill-grant-effect-validation-20261008.md)：同候选8851724完成v853/v854真实Skill撤权效果对照：合法加载/读取/写入及文件内容匹配27项通过；读取后HTTP撤销writer Grant，约6.844秒后观察到实际write_file尝试报错、目标不存在，30项通过。完整Agent基线签名和安装内容不变，剔除请求标识后的OpenShell策略相同且均允许任务输出目录。5回执/2 SEC/3签名Grant快照独立核验；拒写发生在回执之前，无虚构deny。v852因脚本错将正常deployed基线要求为approved而失败，使用新隔离Authority按完整签名内容比较后复测，保留失败且未恢复旧撤销Grant。离线核验器16项及Ruff通过。依赖11663文件/4链接不变，非全栈冻结；剩余生命周期/上下文/四臂/平台/签名继续，11/16保持。

[OPT-08/10 执行上下文撤销与新任务边界](optimization-opt08-context-boundary-validation-20261008.md)：同候选8851724完成v855合法读写、v856读取后仅撤销SEC并实际拒写、v858新合法任务新SEC读写，27/30/27项通过。Skill和Agent完整授权、安装内容、归一化OpenShell可写策略不变；旧SEC保持撤销。10回执/3SEC/1签名撤销/2Grant快照及4请求决定绑定独立核验；3完整通过例占8回执。v857将可信无Skill误当未知归属而预期错误，保留失败；v859无Skill按Agent基线实际允许且文件匹配，23/24项通过，但财务证据护栏替换回答，整例失败且监管退出1/PID0、资源清理确认。离线核验器33项及Ruff通过。依赖11663文件/4链接不变，非全栈冻结；未知归属/到期/并发/四臂/平台/签名及回答护栏归因继续，11/16保持。

[OPT-08/10 可信无 Skill 完整业务复测](optimization-opt08-explicit-no-skill-validation-20261008.md)：可信无Skill完整复测v860同候选30项通过：无Skill加载/无SEC，签名no_skill write allow、实际文件与模型回复标记匹配、监管退出0/PID0及资源清理。只读分类器4项定位v859原提示触发Wiki全文财务证据分支；明确Hermes runtime任务后走既有诊断分类，追加财务问题仍要求证据，未修改护栏。保留v857/v859失败；最终v855/v856/v858/v860四完整通过例占9回执，累计链11回执/3SEC/1撤销/2Grant及4请求绑定独立核验。34项回归与Ruff通过（包含前33项），依赖11663文件/4链接不变；未知归属/到期/并发/四臂/平台/签名继续，11/16保持。

[OPT-08/10 原生元数据通道失联与恢复](optimization-opt08-native-channel-fault-validation-20261008.md)：同候选8851724完成v861原生元数据通道失联与v862新任务恢复：读取后只移走本任务socket，约5.396秒窗口内实际write_file报错、文件不存在、无写入回执；原socket按inode恢复，完整Grant/SEC不变，业务failed/hermes_run_failed且资源释放，故障检查30项通过。新任务加载/读取/写入及结果27项通过。两监管均退出0/PID0；归一化OpenShell可写策略一致。新增5回执/2SEC，完整16回执/5SEC/2新请求绑定与有效Grant签名核验通过；依赖11663文件/4链接不变。未改产品或核验器、不重复无关测试；未知证明/到期/并发/四臂/平台/签名继续，11/16保持。

[OPT-08/10 必需调用标识缺失的真实拒绝](optimization-opt08-call-binding-effect-validation-20261008.md)：同候选8851724完成v863正常代理对照32项和v864缺失tool_call_id负向33项。合法加载/读取后，仅从唯一实际写入HTTP请求移除调用标识，身份/任务/参数/认证/完整Grant和SEC不变；Authority实际409 native_host_unavailable、工具错误、文件不存在，无伪造deny。正常字节透传对照200 allow并实际写入。两例业务completed及监管退出0/PID0，输出OpenShell可写策略一致；新增5回执/2SEC，完整21回执/7SEC/2新请求绑定及Grant独立核验通过。依赖11663文件/4链接不变，代理及自有资源清理；未改产品、不重复无关测试。自然到期/并发/其他错配/四臂/平台/签名继续，11/16保持；已请求原生Windows/macOS接入信息。

[D3 自然到期真实效果](optimization-opt08-natural-expiry-validation-20261008.md)：同候选8851724新增Skill Grant自然到期真实对照：v867到期前合法加载/读取/写入29项通过；v869读取后用pidfd暂停自有Hermes约106秒，正式420秒Grant自然到期后恢复，约0.088秒后观察实际write_file报错、文件不存在，31项通过。SEC及原生子身份尚未到期、Agent基线有效，完整签名内容/归一化可写策略不变，无主动撤销或改时钟。两例业务completed、监管退出0/PID0，资源/配置恢复。新Authority完整8回执/3SEC/2Grant及2请求绑定独立核验，通过例占5回执/2SEC；v865错误SEC截止断言失败、v866未执行、v868缺少os.pidfd_open失败均保留，后用预检查通过的libc pidfd接口复测，不改产品。API依赖11663文件/4链接不变。SEC单独到期、续期/更新、并发、资源入口、最终矩阵/平台/签名继续，11/16保持。

[D3 授权换代与新任务恢复](optimization-opt08-authority-replacement-validation-20261008.md)：同候选8851724完成正式Skill授权换代：独立批准相同内容的新Grant，通过公开compare/plan/commit/activate撤销旧Grant并建立新安装。v870实际读取后暂停自有Hermes约0.368秒完成更新，恢复后实际write_file报错、文件不存在，32项通过；v871显式绑定新安装的独立新任务加载/读取/写入31项通过。Agent基线及Skill字节不变，SEC自身未到期，输出目录仍可写；两例业务completed、监管退出0/PID0，配置/资源恢复。新Authority 5回执/2SEC/4Grant/4安装更新记录及2任务绑定独立核验；新增离线换代签名/关联检查，50项相关回归（新增16项）和Ruff通过。API依赖11663文件/4链接不变。此为相同内容授权换代，不代替内容版本升级或旧授权原地续期；并发/资源入口/最终矩阵/平台/签名继续，11/16保持。

[D3 真实并发请求的排队与权限隔离](optimization-opt08-concurrent-business-validation-20261008.md)：同候选8851724完成v872两个真实业务HTTP请求并发在途：writer实际加载/读取后暂停约2.202秒，reader真实请求在单槽队列等待，三次重叠观察跨度约1.131秒；writer实际写入成功并释放后reader加载自己的只读Skill，实际写入签名deny grant_scope_violation且文件不存在。36项现场检查通过，两业务completed、监管退出0/PID0；同Agent、不同会话/任务/Skill、归一化可写OpenShell策略相同、Grant及源数据不变。完整6回执/2SEC/3Grant及2任务绑定独立核验，离线核验器59项（新增9项）与Ruff通过，API依赖11663文件/4链接不变。证明当前单槽业务架构下真实并发请求的排队及权限隔离，不宣称两个沙箱同时执行或压力容量；内容版本升级、资源/工具入口、最终矩阵/四臂/平台/签名继续，11/16保持。

[OPT-15 回执标识](optimization-opt15-receipt-identity-validation-20261008.md)：固定时钟下相同参数会生成重复 decision ID，历史重复 ID 的审批会选中一条而不拒绝；两项反例已复现。新 ID 改为 128 位随机值，随机源失败不签发；审批在验签链中要求原 hold 与 resolution 唯一且关联一致，歧义返回原有 409。历史样例未改写。定向测试、receipt/skillcontext 包、合同比较、vet 与既有四目标构建记录通过。查询入口、请求边界、token 哈希和原生平台验收继续；总体仍为 11/16（68.75%）。

[OPT-15 重复 ID 查询](optimization-opt15-receipt-lookup-validation-20261008.md)：会话绑定在重复 decision ID 下采用第一条并返回 openshell_decision_missing，已复现。绑定、预留哈希和任务链定位现要求 ID 唯一，重复返回 409 或空哈希；唯一旧 ID 仍走原缺失 Grant 结果。OpenShell server 回归、vet 和四目标编译通过。对账/观察末条覆盖、请求边界和原生平台验收继续，总体仍为 11/16。

[OPT-15 矛盾闭合记录](optimization-opt15-closure-validation-20261008.md)：同一预留先记 deny 再记 allow 时，任务查询采用后一条 allow，已复现。第二条对账或匹配观察现返回 openshell_receipt_ambiguous；单条 deny 对账仍按原投影。OpenShell server 回归、vet 和四目标编译通过。请求边界与原生平台验收继续，总体仍为 11/16。

[OPT-15 请求超限状态](optimization-opt15-request-limit-validation-20261008.md)：超过 4 MiB 的 decide/observe 正文修复前返回 400 invalid decision request，已复现。现返回 413 decision_request_too_large，不进入引擎；畸形正文仍为 400。hold 超过 64 KiB 返回 413，链头不变。定向测试、OpenShell server 回归、vet 和四目标编译通过。线性扫描、生产 assert、token 哈希和原生平台验收继续，总体仍为 11/16。

[OPT-08 Hermes 内容版本](optimization-opt08-content-version-validation-20261008.md)：当前安全提交 8c473439 上，Hermes 原生 V1→V2 更新 16 项通过。两次内容哈希不同；更新替换字节并撤销 V1 Grant，旧决策凭据被拒且没有新回执或文件效果；V2 使用新安装、新身份和新 SEC，实际读取执行，4 条回执验签通过。本地确定性模型，不是日常业务入口，不能并入 v870/v872。日常业务内容版本、资源/工具入口和最终矩阵继续，总体仍为 11/16。

[OPT-08 日常内容版本拒绝](optimization-opt08-content-version-business-validation-20261008.md)：当前安全二进制 aa25999e 与业务 8851724 的 v879 在日常模型上 33 项通过。SKILL.md 由 014ac378 换成 a38f8af2，旧 Grant 撤销；暂停恢复后的 write_file 没有回执，目标文件不存在。已安装监管单元与当前 `SIQ_RUNTIME_ROOT` 合同不一致，产品安装拒绝覆盖；本轮临时对齐后按原字节恢复，模型单元不变。v880 新任务没有读取或写入，工具结果为 native_dispatch_unavailable，没有 V2 Skill 上下文。资源/工具入口、四臂、平台和签名继续，总体仍为 11/16（68.75%）。

[OPT-08 V2 镜像执行](optimization-opt08-v2-image-business-validation-20261008.md)：当前二进制 aa25999e 与业务 8851724 的 v881 在新镜像 `sha256:a3be2a4a`、制品 `c5e3e318` 上 33 项通过。受保护 `SKILL.md` 钉为 `a38f8af2`，读取和写入回执均为 allow 并绑定该安装的 Grant，目标文件存在。`skill_view` 回执本身是 no_skill。冻结镜像目录未改写；监管合同临时对齐后按原字节恢复，模型单元不变。这是镜像已含 V2 字节的新身份，不是旧制品 `070e9423` 上同一身份原地换字节后的续跑。资源/工具入口、四臂、平台和签名继续，总体仍为 11/16（68.75%）。
