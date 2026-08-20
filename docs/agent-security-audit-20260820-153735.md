# 智能体安全管控平台审计报告

## 1. 审计元数据

- 审计时间：2026-08-20 15:37:35 +08:00（Asia/Shanghai）
- 审计仓库：`/home/maoyd/siq/siq-agent-security`
- 审计基线：`main`，HEAD `cf5fbef`
- 审计类型：只读代码审计、架构评估、测试与构建验证
- 重点范围：OpenShell 二次开发、智能体资产发现、风险分类、恶意脚本识别、运行时权限与行为管控、Edge/Connector 隔离、审计治理、跨平台能力
- 本次变更：仅新增本报告，未修改产品源代码

## 2. 结论摘要

当前项目已经形成一个可运行的“智能体安全控制平面 + OpenShell 执行适配器原型”，具备资产候选、证据采集、人工确认、策略审批、签名任务、审计和部分 OpenShell 网络策略闭环。但它目前还不是杀毒软件/EDR，也不是能够在“任何系统”上发现并精准强制管控所有智能体的运行时防护产品。

最重要的判断如下：

1. 资产盘点能力已存在，但覆盖面明显受限。当前真正可用的 Connector 只有 `hermes`、`openclaw`、`docker`、`directory` 四类；没有 `piagent`、`workbuddy/workbudy`、`dify` 的实现，也没有系统进程、systemd、Kubernetes、MCP 服务等通用发现链路。
2. 风险分类不是恶意代码检测。当前分类主要依赖资产名称关键词和可选模型，规则引擎检查的是治理状态，不分析脚本内容、依赖来源、持久化、网络外传、进程行为或提示注入。
3. OpenShell 运行时管控只形成了局部闭环。当前动态网络策略可做有限的 CLI 读回验证；静态文件系统/进程策略的 generation 路径直接抛出错误；工具、模型路由、密钥、数据范围、资源配额和行为事件没有形成实际强制点。
4. 存在一个必须在扩大部署前修复的策略绑定问题：策略 selector 中的 agent ID 没有被可靠解析为运行时目标，部署接口接受调用方直接提供的任意 `target`。这可能造成“给 A 审批的策略部署到 B”或控制台显示与真实执行对象不一致。
5. Connector 运行在主机子进程中，当前没有操作系统级隔离、网络隔离、进程组回收、签名二进制验证或宿主机完整性证明。因此不能把 Connector 当作可信的恶意脚本扫描沙箱。

### 能力成熟度估计

| 能力 | 当前判断 | 说明 |
|---|---:|---|
| 资产发现 | 2/5 | 有四类 Connector 和 smart scan，但发现源、系统覆盖和实例身份不足 |
| 智能体识别/分类 | 2/5 | 名称关键词 + 可选模型；已有基线评估，不等于恶意检测 |
| 恶意脚本检测 | 0.5/5 | 当前只有内容哈希/证据采集，没有静态、动态或信誉检测引擎 |
| 运行时权限管控 | 2/5 | OpenShell 网络动态更新有原型，静态 generation 不可用，许多权限域多为 unsupported |
| 行为管控与响应 | 1/5 | 没有真实行为事件流、阻断证据、隔离/取证/恢复闭环 |
| 审批、审计、租户治理 | 3.5/5 | 签名、审批、outbox、租户和 fail-closed 设计较完整，但对象绑定仍需加强 |
| 跨平台能力 | 1/5 | 当前实现明显依赖 Linux/OpenShell/主机命令，尚不足以宣称任意系统支持 |

## 3. 已有基础与值得保留的设计

项目的安全基础并非空白，以下设计方向是正确的，应继续保留并扩展：

- 以 Evidence、Candidate、Asset、Policy、Deployment、Audit 组成控制面数据链路，适合演进为统一资产与策略事实源。
- `AGENTS.md` 明确要求租户从身份派生、秘密不落库不进日志、审计和状态同事务、模型不能直接产生有效权限、Edge 凭据只存哈希、生产禁止 SQLite 和开发 Header。
- Connector 协议采用受限子进程和 NDJSON，具备超时、输出上限、环境变量白名单等基础约束。
- Edge 任务使用签名和过期时间，策略发布路径在缺乏独立验证器时不会伪造为有效，这种 fail-closed 取向是正确的。
- 策略编译器会显式记录 unsupported execution point，说明项目已经意识到控制平面声明不等于执行平面能力。
- OpenShell 适配器没有把长期方案简单地做成不可维护的分叉，ADR 已经选择适配器和能力探测方向。
- 本地 Python 测试、Python 编译检查和 Web 构建通过；说明当前基础工程仍可继续迭代。

## 4. 主要发现

严重度定义：

- P0：会导致核心安全承诺失效、错误执行或形成高影响攻击路径，扩大部署前必须处理。
- P1：重要能力缺口或可被现实攻击利用，应在产品化前处理。
- P2：工程质量、可维护性、覆盖率或验证能力问题，应纳入近期迭代。

### P0-1：策略 selector 与真实运行时目标没有强绑定

证据：

- `apps/control-api/app/routers/policies.py:45-55` 只验证 selector 非空，没有验证 agent ID 属于当前租户、环境或具体运行实例。
- `apps/control-api/app/routers/policies.py:328-350` 的部署请求接受调用方传入的 `body.target`。
- `apps/control-api/app/routers/policies.py:392-405` 使用任意 target 调用适配器，编译器接收到的 selector 没有成为服务端目标解析依据。
- `apps/control-api/app/routers/inventory.py:881-932` 在计算资产 enforcement 状态时，也主要按有效部署和策略匹配判断，没有验证部署 target 是否对应该资产实例。

影响：策略 A 可能被部署到 sandbox B；控制台可能把 A 标记为已管控，而实际受控对象是 B。对于权限收紧、网络阻断和密钥访问控制，这是越权和错误执行，不是单纯展示问题。

建议：

- 引入不可变的 `AgentIdentity`、`AgentInstance`、`RuntimeBinding` 三层身份模型。
- `RuntimeBinding` 至少包含 tenant、environment、agent_instance_id、backend、backend_target_id、启动证明/版本、创建时间和撤销状态。
- 部署 API 只接受 `agent_instance_id` 或服务端生成的 binding ID，不接受任意原始 target；target 必须由服务端根据 binding 解析。
- OpenShell policy snapshot、deployment、permission fact、behavior event 全部引用同一个 instance/binding ID。
- 增加负向测试：租户内 A 的策略不能部署到 B；跨租户 agent ID、环境 ID、sandbox ID 必须拒绝；binding 被撤销后不能继续发布。

### P0-2：静态 OpenShell 策略没有可用的真实执行路径

证据：

- `apps/control-api/app/adapters/openshell/cli_backend.py:295-299` 的 `create_generation()` 直接抛出 `AdapterError`，说明 sandbox generation 受 protobuf 解码问题影响且当前不可部署。
- `apps/control-api/app/adapters/openshell/policy_compiler.py:67-107` 会把文件系统、进程和部分网络能力编译为静态生成内容，但编译成功不代表已经执行。
- `cli_backend.py:247-293` 的现有路径主要处理动态更新和 revision 合并。

影响：文件系统只读/可写边界、进程限制等高价值控制无法通过当前真实后端闭环。若上层把 compiled 或 planned 当作 effective，会产生严重的安全错觉。

建议：

- 在 generation 路径修复前，任何包含静态字段的策略必须在审批或部署前明确拒绝，不能进入 effective 状态。
- 正式实现 `create -> validate -> verify -> cutover -> observe -> rollback` 生命周期，并记录 generation ID、目标 binding、策略摘要、OpenShell 版本、探测结果和验证证据。
- verify 不应只读回 YAML 或 revision；必须做真实 allow/deny fixture，覆盖文件、进程、网络和失败关闭行为。
- 失败、超时、版本不兼容、能力探测不确定时，状态只能是 failed/unknown，不得是 effective。

### P0-3：当前没有恶意脚本检测引擎

证据：

- `apps/control-api/app/classification.py:41-68` 的 baseline 主要从资产名称关键词判断 agent 候选，输出 confidence。
- `classification.py:87-132` 发送给模型的输入主要是 `name` 和 `framework`，不是脚本内容、依赖图或行为数据。
- `apps/control-api/app/rules.py:41-185` 的五类规则检查无 owner、心跳过期、证据过期、共享凭据、无有效权限等治理状态。
- `apps/control-api/app/models.py:140-173` 的 Evidence 支持 content hash 和 payload_ref，但 Connector 协议有意不上传原始脚本；仓库中没有 YARA、IOC、AST、SBOM、信誉、沙箱执行、隔离、quarantine 等实现。
- `docs/eval-baseline.md` 的 6/8 召回率衡量的是“是否为智能体候选”，不是恶意样本识别率。

影响：项目目前可以发现和分类部分智能体资产，但不能回答“脚本是否恶意”。如果对外宣称具备杀毒式扫描，容易造成严重的产品安全承诺偏差。

建议：

- 将“资产识别”和“威胁检测”拆成两个独立分析域。
- 采集阶段只做哈希、类型、大小、权限、路径、来源、签名、依赖锁定信息和受控脱敏内容；禁止在主机采集器内直接执行未知脚本。
- 静态分析至少覆盖 AST/解释器语法、危险命令、下载执行、凭据读取、持久化、反射/混淆、外联/外传、动态加载、供应链来源和提示注入载荷。
- 动态分析必须在一次性、无凭据、无主机网络、可回收快照的 detonation 环境中完成，并产生进程/文件/网络行为事件。
- Finding 需要包含规则 ID、证据哈希、命中位置、置信度、严重度、分析器版本和可复现输入摘要；模型只能给出建议，不能单独决定 allow。

## 5. P1 级问题与能力缺口

### P1-1：OpenShell 策略模型丢失高层语义

证据：`apps/control-api/app/adapters/openshell/contracts.py:40-67` 和 `policy_compiler.py:33-107` 的能力与快照模型主要覆盖 filesystem、network、process、enforcement mode。`cli_backend.py:378-410` 将网络规则压缩为 `host:port`，路径只对 `**` 做特殊处理，方法、协议、L7 请求语义没有保留。

当前模型还把 tools/tool_policies、secrets、data_scope、resources、audit、exceptions 归为其他执行点。对于智能体产品，这些正是 MCP 工具调用、模型路由、密钥使用、数据外传和资源滥用的核心控制面。

建议把能力拆为版本化 capability document，至少区分：

- sandbox 生命周期与身份；
- 文件、进程、系统调用；
- L3/L4 网络；
- L7 HTTP/DNS/协议与请求条件；
- MCP/tool 调用与参数约束；
- 模型/Provider 路由；
- 凭据注入、用途和目的地绑定；
- CPU、内存、磁盘、并发和 token 配额；
- 结构化行为事件和审计回执。

每项能力都要有 `supported / unsupported / unknown`，并明确是 advisory、observe 还是 enforce。

### P1-2：verify 目前更像配置读回，不是行为验证

证据：`cli_backend.py:301-328` 通过轮询 revision 和检查 network 列表验证，且依赖一个合成的拒绝 endpoint。`stream_events()` 在 `cli_backend.py:350-355` 返回的是 policy list 文本伪装成事件，而非真实行为事件流。

建议为每个执行点提供可重复 fixture：允许样例、拒绝样例、边界样例、适配器异常样例。验证结果必须包含请求、预期决策、实际决策、事件 ID、策略 revision 和时间窗口。没有行为证据时只能标记 readback_verified，不能标记 enforcement_verified。

### P1-3：Connector 隔离不足，不能作为可信扫描沙箱

证据：

- `edge/agent/connector.go:145-155` 使用普通 `exec.CommandContext` 启动 Connector。
- `connector.go:183-193` 只 kill 直接子进程，没有进程组、Linux cgroup/namespace/seccomp、Windows Job Object 或 macOS sandbox 约束。
- Connector 的 `NetworkAccess=false` 只是声明式 capability，不是主机网络隔离。
- `ResolveConnectorBin` 允许 `SIQ_CONNECTOR_BIN_DIR`、PATH 或显式路径解析，没有签名、摘要、来源和版本验证。
- `docs/adr/0008-plugin-trust.md` 已明确插件签名/隔离属于后续阶段，当前 subprocess 隔离弱于容器。

建议：

- Linux：独立低权限用户、mount/user/pid/net namespace、seccomp、Landlock/cgroup、只读根文件系统、无凭据环境和独立工作目录。
- Windows：Job Object、低权限 token、受限 ACL、网络防火墙规则和签名验证。
- macOS：sandbox profile、受限文件访问、代码签名/公证检查和网络控制。
- 所有平台：进程组/进程树回收、CPU/内存/文件/输出上限、崩溃恢复、二进制 digest allowlist、签名密钥轮换。
- Connector 只读采集能力和可执行分析能力分离；未知文件不应在宿主机上下文执行。

### P1-4：智能体发现覆盖不足，且没有统一实例身份

证据：

- `apps/control-api/app/schemas.py:175-183` 的 ConnectorName 只有四类。
- `edge/agent/connector.go:343-377` 的二进制解析也只允许四类。
- `apps/control-api/app/routers/inventory.py:106-175` 的 smart scan 主要处理 Hermes、OpenClaw 和 Docker。
- `connectors/docker/docker.go:243-245` 只扫描带 `siq.agent=true` 标签的容器，不是所有候选容器。
- AgentInstance 模型位于 `apps/control-api/app/models.py:125-138`，但仓库中没有发现除模型定义外的写入路径；`inventory.py:935-959` 主要读取它。
- 仓库未发现 `piagent`、`workbudy/workbuddy`、`dify` 的实现。
- schemas 中出现 `kubernetes`、`systemd`、`process_list` 候选来源，但没有相应完整 Connector/ingestion 路径。

建议建立三层发现机制：

1. 应用级：标准目录、配置、虚拟环境、包管理器、入口脚本、Docker/K8s 元数据。
2. 运行级：进程树、监听端口、父子关系、systemd/launchd/Windows service、容器和编排对象。
3. 协议级：MCP server、工具注册、Provider、凭据引用和出站目的地。

所有发现结果先进入 canonical `AgentIdentity`，再关联可变化的 `AgentInstance` 和 `RuntimeBinding`。不要用名称、路径或 sandbox ID 充当长期身份。

### P1-5：Edge 任务可能被并发重复领取

证据：`apps/control-api/app/routers/environments.py:201-223` 查询 pending tasks；`environments.py:272-289` 的状态更新与领取不是一个明确的原子 claim 操作。`edge/agent/client.go:163-173` 的 FetchTasks 也没有显示出原子认领语义。

影响：多个 Edge 或重试可能同时处理同一任务，造成重复扫描、重复回执或状态竞争。虽然批次 digest 有一定幂等性，但不能替代任务级 exactly-once/at-least-once 设计。

建议使用数据库事务中的 `SELECT ... FOR UPDATE SKIP LOCKED` 或等价 claim token，增加 leased_at、lease_owner、attempt、idempotency key 和明确的 receipt deduplication。

### P1-6：Directory 采集的字节预算存在越界风险

证据：`connectors/directory/directory.go:272` 按剩余预算调用读取函数；`directory.go:350-363` 在 `maxBytes <= 0` 时回退到 1 MiB。剩余预算为 0 时，helper 仍可能读取默认大小，随后才在上层发现超限。Hermes/OpenClaw 也存在“截断但没有明确 truncation 字段”的证据语义问题。

建议：读取函数必须接收严格的非负剩余预算；预算为 0 时返回明确的 truncated/skipped 结果；Evidence 增加 `bytes_read`、`bytes_limit`、`truncated`、`content_type` 和 `redaction_status`，避免把不完整内容误当成完整分析结果。

### P1-7：确认候选时缺少跨租户对象引用校验

证据：`apps/control-api/app/routers/inventory.py:669-702` 直接使用请求体中的 `system_id` 和 `owner_user_id`，没有看到同租户、存在性和授权关系的完整验证。`System` 与 `AgentAsset` 的关联也没有体现复合租户约束。

建议所有外键式业务引用使用“对象存在 + tenant_id 相同 + 调用者有权限”的统一校验；数据库层补充复合唯一键/约束，避免仅依赖应用层。

### P1-8：候选制品指纹和框架属性在入账时丢失

证据：

- `packages/contracts/candidate.schema.json:27-33` 和 `apps/control-api/app/schemas.py:225-226` 定义了 `artifact_digest`、`attributes` 等候选特征。
- `apps/control-api/app/routers/inventory.py:350-358` 创建 `AgentAsset` 时只写入 name、framework、source、evidence_ids 等字段，没有保留候选的 artifact digest 和 attributes。
- `AgentAsset` 模型没有对应的制品摘要/属性字段；`AgentInstance` 虽有 `artifact_digest`，但当前没有发现可靠的实例写入链路。

影响：后续无法稳定做镜像/安装包/配置指纹变更检测、信誉查询、版本漂移和供应链基线比较。Evidence 的 hash 只能证明某条证据内容的稳定性，不能替代 AgentAsset 的制品身份。

建议把制品摘要、脱敏属性和来源版本纳入规范化 `AgentIdentity` 或 `AgentInstance`，并在每次重新发现时做版本化观察；保留原始 candidate 到 canonical asset 的字段映射，禁止入账时静默丢字段。

### P1-9：发现入口依赖 Docker 标签，会静默漏掉影子智能体

证据：`connectors/docker/docker.go:243-245` 使用 `docker ps --filter label=siq.agent=true`，只有主动加标签的容器才会进入 Connector。

影响：未打标签的智能体容器不会进入候选、风险和治理链路，恰好绕过平台需要解决的影子智能体盲区。这不是普通的分类误差，而是扫描入口的静默漏报。

建议先枚举全部可见容器，再根据镜像、入口命令、进程树、挂载、端口、环境变量名称（不采集值）和协议特征分类；标签只能作为高置信提示或纳管标志，不能作为发现前置条件。对权限不足或 Docker daemon 不可达也要产生明确的 coverage gap 事件。

### P1-10：基线分类没有真正使用 framework，且没有可解释的聚合风险评分

证据：

- `apps/control-api/app/classification.py:41-68` 的 `_baseline_classify` 只读取 `asset.name` 和 owner 是否存在；`system_candidates`、`capability_hints` 固定为空。
- Provider 路径在 `classification.py:87-132` 虽然把 name/framework 发送给模型，但仍没有脚本内容、依赖图、权限事实或行为事件。
- `apps/control-api/app/rules.py:41-185` 产生的是逐条治理规则 Finding；仓库没有看到由暴露面、行为、信誉、漏洞和治理状态合成的稳定 `risk_score` 及其版本化解释。

影响：当前“识别”主要是名称启发式，“风险高低”主要是单条治理告警严重度，无法形成跨资产可比较、可审计、可解释的风险排序。

建议：先让 baseline 使用 framework、source_type、artifact digest、权限事实和证据新鲜度等确定性信号；再引入版本化风险评分：`Risk = f(exposure, behavior, reputation, vulnerability, governance)`。每个分项必须关联 Evidence/Finding，模型只能作为建议项，人工覆写必须记录原因、操作者和有效期。

### P1-11：执行模式合同与 OpenShell CLI 实际能力不一致

证据：

- `apps/control-api/app/adapters/openshell/contracts.py:81` 支持 `audit_only`、`warn`、`block` 三种模式。
- `apps/control-api/app/routers/policies.py:362-366` 在 `openshell-cli` 后端下硬拒绝非 `block` 模式。
- `apps/control-api/app/adapters/openshell/cli_backend.py:243` 的 `read_effective_policy` 无论实际状态如何都返回 `enforcement_mode="block"`。

影响：策略模型宣称有渐进执行档位，但当前 OpenShell 路径只能阻断或拒绝；读回又会把真实状态归一成 block，导致审计、漂移和控制台可能无法区分 observe/warn/block。

建议在 OpenShell 尚未支持 observe/warn 前，把 capability 明确标为 unsupported，并在 API/UI 显示“该后端不支持”，不要接受后再硬编码转换。实现模式后，readback 必须来自真实后端状态，并为每个模式提供对应行为 fixture。

## 6. P2 级问题

### P2-1：静态质量检查当前不干净

`uv run ruff check app` 失败于两个 B018 useless-expression：

- `apps/control-api/app/adapters/openshell/cli_backend.py:104:17`：`parsed.port`
- `apps/control-api/app/config.py:101:17`：`parsed.port`

这两个表达式看起来是为了触发 URL 解析校验，但应改为显式访问并使用结果，或明确捕获解析异常。建议纳入 CI 阻断条件。

### P2-2：Go 验证链在当前环境不可执行

Edge 和四个 Connector 的 Go 测试/`go vet` 未运行，因为当前环境没有 `go` 命令。该结果不是代码失败，但意味着本次报告没有完成 Go 层编译和运行时验证。应在 CI 中固定 Go 版本、执行 `go test ./...`、`go vet ./...` 和竞态测试，并把 Connector 恶意输入、超时、子进程逃逸和路径穿越作为测试集。

### P2-3：OpenShell 版本与能力声明存在漂移

- `cli_backend.py:173-187` 的 probe 返回硬编码 `v0.0.83-policy-v1` 和固定 capability 值。
- README/ADR/compatibility 文档已经出现 v0.0.104 迁移和能力变化，但适配器仍保留 v0.0.83 假设。
- `docs/adr/0009-openshell-version-path.md` 标注 V1-V5 语义验证和迁移 runbook 仍需完成。

建议 probe 只返回真实检测结果，所有 capability 都由实际 CLI/API 探测和语义 fixture 得出；版本升级采用兼容矩阵和上游版本 CI，而不是修改一个硬编码版本字符串。

### P2-4：HTTP Client 与 CLI Backend 存在重复合同

仓库同时存在 `apps/control-api/app/adapters/openshell/client.py` 和 `cli_backend.py` 两套适配路径，而部署路由实际主要走 CLI。长期应保留一套稳定的 `EnforcementBackend` 合同，把 HTTP/CLI 作为 transport 实现，避免能力、错误码、revision 和验证语义分叉。

## 7. 对 OpenShell 二次开发的建议

### 7.1 定位

OpenShell 应作为“受管运行时执行后端”，而不是整个跨平台主机防护产品。主机级发现、进程级遥测、文件扫描和平台原生强制点必须由 Linux、Windows、macOS 各自的 Host Sensor/Enforcement Provider 提供；OpenShell 只负责它能证明执行的 sandbox 范围。

进一步说，直接运行在宿主机上的 Hermes、PiAgent、WorkBuddy 等实例如果没有进入 OpenShell sandbox，OpenShell 不在其实际执行路径上，不能对它们宣称精准强制。`RuntimeBinding` 必须记录执行后端和验证状态；没有 OpenShell binding 的实例应转交 Host OS Provider，若该平台也没有强制能力，只能处于 Observe/Unknown，不能显示 enforced。

### 7.2 不建议长期维护大分叉

以版本化 Adapter、Capability Handshake、上游兼容测试和可回滚 migration layer 为主。二次开发只在确实缺失的安全执行点增加上游可接受的扩展；不要把控制平面业务模型、租户审批和风险引擎深度嵌入 OpenShell fork。

### 7.3 必须补齐的适配器合同

```text
probe() -> backend version, capabilities, trust state
resolve(binding) -> immutable target identity
compile(policy, capabilities) -> artifact + unsupported reasons
plan(artifact, target) -> change set + preconditions
apply(change set) -> deployment revision
verify(revision, fixtures) -> behavior evidence
observe(revision) -> structured runtime events
rollback(revision) -> rollback evidence
```

所有返回值都应带 tenant、binding、policy digest、backend version、capability snapshot 和时间戳。`unsupported`、`unknown`、`readback_verified`、`enforcement_verified` 必须是不同状态。

### 7.4 建议的 OpenShell 适配器验证矩阵

每个支持的 OpenShell 版本至少执行：

- 网络允许/拒绝、DNS、重定向和超时；
- 文件读取/写入/路径逃逸；
- 进程启动、子进程、后台化和资源上限；
- middleware/interceptor 或等价的 L7/MCP 事件；
- 凭据未注入、用途不匹配、目的地不匹配；
- backend 重启、控制平面失联、策略回滚和版本不兼容；
- target A/B 绑定负向测试；
- 有效策略被篡改、revision 不一致和旧回执重放。

## 8. 建议的目标架构

```text
Host Sensor / Runtime Provider
        |  discovery, process, fs, network, service, MCP
        v
Canonical Agent Identity + Agent Instance + Runtime Binding
        |                         |
        v                         v
Evidence / Analysis Plane     Policy Decision Plane
(static, reputation,         (risk, approval, selector,
 detonation, behavior)         capability, exceptions)
        |                         |
        +------------+------------+
                     v
              Enforcement Plane
       (OpenShell / OS provider / K8s)
                     |
                     v
          Events, Receipts, Drift, Audit
```

建议统一建模以下对象：

- `AgentIdentity`：框架、版本、来源、组织归属、稳定指纹。
- `AgentInstance`：具体安装、配置、主进程、容器或编排对象。
- `RuntimeBinding`：实例与 OpenShell sandbox/OS provider 的不可变绑定。
- `Evidence`：哈希、来源、采集时间、内容类型、截断和脱敏状态。
- `Finding`：规则、严重度、置信度、证据引用、分析器版本、处置建议。
- `BehaviorEvent`：进程、文件、网络、工具、模型、凭据和资源行为。
- `PolicyDecision`：决策输入、策略版本、能力快照、决策结果和解释。
- `QuarantineCase`：隔离、证据保全、密钥撤销、恢复审批和最终处置。

产品模式应明确区分：

- Observe：发现、分析、告警、审计，不声称已经阻断。
- Enforce：只有目标被可信 binding 管理且执行点经过行为验证时，才允许阻断并展示 enforced。
- Unknown/Degraded：失去心跳、能力探测失败、回执无效或版本不兼容时，进入降级状态，不自动放宽权限。

## 9. 分期改造路线

### P0：产品化前必须完成

1. 修复 selector 到 runtime target 的不可变绑定；所有策略、事实、审计使用统一实例 ID。
2. 修复或禁用静态 OpenShell generation；未验证的文件/进程策略不得标记 effective。
3. 将能力状态拆成 supported/unsupported/unknown 和 readback/enforcement verified。
4. 建立最小威胁检测流水线：哈希、类型识别、规则/AST、危险行为特征、隔离分析、Finding 和 quarantine 状态。
5. Connector 二进制签名/digest 校验、低权限执行、进程组回收、网络隔离和无凭据运行。
6. 明确产品支持矩阵，停止使用“任何系统、所有智能体”这类未经平台执行点证明的表述。

### P1：形成可销售的闭环

1. 增加 Linux process/systemd、Windows service/process、macOS launchd/process、Kubernetes、MCP server 等发现源。
2. 为 OpenClaw、Hermes、Piagent、WorkBuddy、Dify 建立 fixture-driven Connector；未知框架进入 generic discovery，而不是静默漏报。
3. 去掉 Docker 标签作为发现前置条件；保存 artifact digest、脱敏 attributes 和 framework/source 事实，建立制品指纹变更检测。
4. 实现结构化行为事件和真实 allow/deny fixture 验证。
5. 增加 secrets/data scope/tool policy/model route/resource quota 的明确执行后端，不能只放在 `unsupported` 列表。
6. 实现任务原子 claim、lease、重试和回执去重。
7. 修复证据截断和跨租户对象引用校验。
8. 实现可解释、版本化的风险评分，并让 `audit_only/warn` 只在后端确实支持且有行为验证时开放。

### P2：规模化与长期维护

1. 建立 OpenShell 版本兼容矩阵、上游升级 CI、迁移 runbook 和自动回滚。
2. 独立部署 receipt verifier/attestation，降低对 Edge 自报状态的信任。
3. 建立规则、YARA/IOC、信誉和模型版本的签名更新机制，支持离线缓存和回滚。
4. 引入 OCSF 或等价事件规范，提供 SIEM、工单和取证导出。
5. 建立跨平台安装器、升级、卸载保护、Edge 防篡改和离线失联处置。

## 10. 验收指标建议

上线前至少建立以下可量化门槛：

- 受支持框架 fixture 发现召回率 >= 95%，版本和入口识别准确率单独统计。
- 未知框架必须进入 generic candidate，不能因不认识而消失；漏报率持续可观测。
- 扫描新鲜度目标 < 60 秒，重复任务率 < 0.5%。
- 恶意样本集按下载执行、凭据窃取、持久化、外传、混淆、提示注入等类别统计召回率和误报率；目标召回率 >= 95%，误报目标按类别控制在 1% 至 5% 并保留人工复核。
- 目标绑定错误率必须为 0；跨 tenant、跨 environment、跨 instance 部署负向测试全部通过。
- 本地策略决策 p95 < 100 ms；撤销或阻断在定义的心跳/事件窗口内生效，例如 <= 5 秒，并明确离线行为。
- 文件、进程、网络、MCP/tool 至少各有允许、拒绝、异常、回滚四类行为测试。
- 没有证据、能力未知、回执失效、版本不兼容时，不能进入 effective，也不能自动放宽权限。
- 审计事件完整率 100%；每次决策可追溯到 tenant、instance、binding、策略 digest、能力快照和执行回执。

## 11. 本地验证结果

| 检查 | 结果 |
|---|---|
| `uv run pytest -q` | 通过 |
| `python -m compileall -q app` | 通过 |
| `npm run build`（`apps/web`） | 通过，Vite 构建成功 |
| `uv run ruff check app` | 失败，2 个 B018，见 P2-1 |
| Go tests/vet | 未执行，环境缺少 `go` 命令 |
| `git diff --check` | 通过 |

测试通过只说明现有测试集没有发现回归，不代表上述能力缺口已经被覆盖。尤其需要补充 target binding、恶意 fixture、Connector 逃逸、静态策略 generation、真实行为验证和跨租户引用的负向测试。

## 12. 审计限制

- 本次没有连接生产控制平面、真实 Edge 集群或真实 OpenShell gateway，因此没有把线上运行时状态当作代码事实。
- Go 工具链缺失，Edge/Connector 的编译、运行时和竞态验证未完成。
- 恶意样本、跨平台主机和实际 OpenShell 多版本环境未在本机执行动态验证。
- 报告中的“成熟度”是基于源码和现有测试的产品判断，不是独立认证或渗透测试结论。

## 13. 最终判断

项目适合继续沿“统一智能体资产、风险、策略和审计控制平面”方向发展，OpenShell 作为首个受管运行时后端是合理的。但下一阶段的核心不是继续增加更多策略字段，而是先把三件事做实：

1. 任何策略都必须绑定到不可伪造、可验证的真实 AgentInstance/RuntimeBinding；
2. 任何“已阻断”都必须有真实行为验证和执行回执；
3. 任何“恶意检测”都必须由独立分析与隔离流水线提供证据。

在这三点完成前，产品定位应表述为“智能体资产发现、风险治理与部分受管运行时策略控制平台”，不应表述为已经具备完整的杀毒、EDR 或全平台精准管控能力。
