# 安全优化实施进度（2026-10-07）

状态源：[optimization-tasks-20261007.json](optimization-tasks-20261007.json)。本文件为其阅读视图，更新状态先修改 JSON，再刷新本视图。

方案：[优化开发方案](SIQ_Agent_Security_优化开发方案_20261007-102651.md)。

基线：`c41347579ebe67c7f732d0e523722e489f831039`。分支：`codex/security-optimization-20261007`。

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
| OPT-09 | OpenShell行为证据 | planned | 待结合对应模块继续核对 |
| OPT-10 | 同候选业务回归 | planned | 待结合对应模块继续核对 |
| OPT-11 | 连接器可信执行 | implementing | 待结合对应模块继续核对 |
| OPT-12 | 钩子完整性 | planned | 待结合对应模块继续核对 |
| OPT-13 | 交付安全头 | done | 待结合对应模块继续核对 |
| OPT-14 | 扫描进程隔离 | implementing | SEC-F08 |
| OPT-15 | 跨平台验收与有界清理 | planned | SEC-F06 |

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
