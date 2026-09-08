# Provenance-Bound Effect Security V1 开发台账

- 用户开发模板：[原文，逐字保存](templates/provenance-bound-effect-v1-development-template.md)。
- 模板 SHA256：`9e6d575d0f3bd1639eaa57b59c59e503849b332d86e76289ba1fbbfb998d9817`。
- 实际起点：`d001c4d2c1b7a1230604e8b2ecf813a39deb251c`；分支：`codex/provenance-bound-effect-v1`。
- 本轮开发目标以此模板 §0–120、INV-1–7 和 45 项 DoD 为准；旧 Provenance 优化计划仅作为背景，不覆盖本模板。
- 状态：已设置为持续开发目标，进行中；A/R/B 主链路与 C 效果证据、Completion 已落地；继续恢复、网络归档、平台集成与 D/G 验收。不向 main 直接写提交，不修改 GitHub Ruleset 或实际用户平台配置。

| 工作包 | 范围 | 状态 |
| --- | --- | --- |
| A1 | Authority Hard Gate、回执分层、required/optional × 三模式、历史签名兼容 | 本地验收通过；全仓 CI 待最终集成 |
| A2 | 移除 caller cwd 授权、ContextAssertion、受信 workspace 与重放/到期 | 本地 admin 签发版本验收通过；外部 attestor 未实现 |
| R | 统一 RuntimeActionDescriptor，高影响参数、shell unknown，六类消费者统一 | 六类消费者已统一；V3 高影响参数默认来源约束本地验收通过 |
| B1 | 签名 provenance、issuer registry、范围/到期/撤销、容量、不可变存储 | 签名 registry/图存储、管理与受限上报 API 已实现；固定向量与完整验收待补齐 |
| B2 | Intent V3 双读、参数内容/来源绑定、MCP 默认不可信、派生/聚合防升级 | V3 双读、来源匹配、确定性选择与 MCP 组件验收通过；native 自动采集待完成 |
| C1 | EffectEvidence、独立 capability、文件 observer、可控网络 oracle | 文件采样 API、网络 oracle、材料归档与提交 API 已实现；平台调度待补齐 |
| C2 | 幂等/冲突/越权效果事件、CompletionStatus、恢复 | Completion API、历史动作与审批时间复核已实现；pending持久恢复待完成 |
| D | 独立 benchmark，至少20场景、攻击对应 benign、D0–D5 分母与阶段性能 | 20对组件场景实际运行通过；阶段性能、完整证据包及CI待完成 |
| G | ADR 15–17、威胁27–35、能力矩阵、README、CODEOWNERS、CI smoke/nightly | ADR及API规格已增量更新；威胁/能力/README/CI与最终报告待整体验收 |
| 验收 | 45项DoD、P01–10/C01–04/E01–05、race/全仓CI、最终工程报告 | 待完成 |

完成证据必须绑定具体命令/源码/回执/CI；未覆盖平台保留 unverified。

## 整体进度估算（2026-09-08）

依据当前分支截至 `4dae986` 的代码与已记录本地验证，完整目标的工程进度约 **65%–70%**。此为结合实现、集成及验收剩余工作量的区间估算，不是45项DoD正式通过率，也不按提交数或代码行数计算。

- A/R：核心能力及主要本地回归已完成；最终全仓与平台验收仍需确认。
- B：签名来源、V3、高影响约束、受限上报、确定性派生和MCP组件链路已实现；平台自动采集及完整兼容/安全证据待补齐。
- C：文件真实采样、独立capability、签名证据、受控网络oracle、Completion API和历史动作复核已实现；pending恢复、网络材料归档及网络完成要求仍缺。
- D：独立D0–D5 benchmark、至少20组攻击/benign场景及指标/性能报告尚未完成，是主要剩余工作包。
- G/验收：需要统一文档/能力矩阵、CI smoke/nightly、全部平台回归、全仓CI和最终工程报告。既有Go race/vet/四平台通过不能替代这些验收。


## A1 实际验证（2026-09-08）

- 修复前新增 `TestMandatoryAuthorityCannotBecomeAdvisoryAllow/warn/intent_binding_missing` 和 `TestCallerCWDDoesNotGrantWorkspaceWrite`，实际执行失败：required+warn 缺绑定仍 allow；伪造 cwd 使未授权 shell 写路径 allow。修复后通过。
- `apps/agentshield: go test -race ./...` 通过，包含 15 类 Authority 错误 × 三模式、required/optional 撤销矩阵、never-bound 策略兼容、HTTP deny 后伪造 Observe 拒绝、历史签名与新字段篡改负例。
- `apps/agentshield: go vet ./...`、linux/amd64、linux/arm64、darwin/arm64、windows/amd64 编译通过；产物在 `/tmp/siq-authority-*`。
- `apps/control-api: .venv/bin/pytest app/tests/test_schema_contracts.py -q` 67 项通过；新增历史/当前/Authority invalid 三份 Go 回执与三模式非法组合测试。Ruff 对修改测试通过。
- `apps/web: npm run build` 通过（包含 TypeScript 编译）。
- A1 提交时已删除 cwd 隐式写权限；后续 A2 签名上下文实现与证据见下节。
- A1 不提供断连客户端的独立授权证明；离线模式和外部平台能力仍按实际证据标注。

## A2 实际验证（2026-09-08）

- 新增 `context-assertion.v1.schema.json`，仅允许 workspace_root；管理端签发和读回，决策端只能引用。复用 Intent store 的不可变发布与签名实现，独立 `trustedcontext` 包验证请求绑定。
- `TestContextIntegrityScopeReplayAndExpiry` 覆盖任务/会话/Agent/平台/调用/参数跨域重放、到期边界、未来声明、签名和 issuer 篡改、重复 ID 与重启读取；`TestContextPublicationConcurrencyAndSample` 覆盖并发签发/读取及固定向量；`TestContextCapacityAndMalformedStorageFailClosed` 验证容量上限和路径穿越。
- `TestContextReferenceHardGateAndRecovery` 覆盖三模式决策与重启；`TestContextCannotReplaceGrantAndApprovalRechecksExpiry` 验证有效声明不能替代 Grant，并在审批后到期且重启时拒绝执行前复查。
- `TestContextIssuanceIsAdminOnly` 使用原始 HTTP 请求验证 decision token 对签发和读回均为 403。旧 `call()` 辅助函数会自动替换 admin token，不能用作权限负例；本轮负例没有沿用该替换行为。
- `go test -race ./...` 通过；Python 合同测试 69 项通过，包含 Go 签名由 Python Ed25519 和 canonical bytes 交叉验证、额外 claim 拒绝；修改测试 Ruff 通过。
- `go vet ./...`、四平台编译及 Web `npm run build` 通过；本轮编译产物 `/tmp/siq-context-*`，Web 构建日志 `/tmp/siq-context-web-build.log`。
- 同一 tool_call_id 的相同请求可在到期前重试，声明不是一次性执行租约。workspace_root 不扩大 Grant/Intent；不声称已接入外部 attestor 或支持 Windows 原生路径语义。

## R 实际验证（2026-09-08）

- 新增 `runtimeaction.Describe`，归并工具效果分类、出网/文件提示、高影响 JSON Pointer、结构化资源与解析错误。Grant/Intent/taint/trifecta/receipt 和 hold-status 使用此入口；旧 Normalize/ExtractResources 只作兼容委托。Provenance evaluator 尚未实现，六消费者最终验收仍待 B。
- 原 `receipt` 的 egressTools/shellTools/fileTools 与命令/URL/路径提取正则已移至统一语义包；安全策略的 secret/PII 检测继续由原检测器负责，不误当工具分类。
- `TestDescriptorInterpreterAliasesRemainUnknown` 覆盖 bash/sh/python/node/powershell 等 9 个别名与嵌套命令，始终包含 process.exec+unknown。`TestDescriptorHighImpactPointersAndCompatibility` 覆盖嵌套/转义路径、兼容入口和无效结构化资源；`TestDescriptorFileAliasesShareWriteChecks` 覆盖文件别名及未知 Connector 的高影响字段。
- `TestFileAliasesCannotBypassGrantedWriteScope` 在 `b450d9e` 的临时 `git archive` 副本上实际失败：write/edit/remove 对 `/secret/report` 都 allow；当前工作树全部拒绝，且显式授权的 `~/work/out/report` 仍 allow。未执行命令或创建目标文件。
- `go test -race ./...` 通过；补充文件别名测试单独运行通过。`go vet ./...` 和四平台交叉编译通过，产物 `/tmp/siq-descriptor-*`。
- 文本 Hosts/Paths 只触发额外安全检查，不是独立效果证明；shell 目标不生成结构化 Resource。后续 B/D 继续验证高影响参数约束与性能成本。

## B1 合同基础（2026-09-08，进行中）

- ADR-016 和开发规格先定义来源类型/可信度分离、issuer 权限、内容摘要、全部父引用约束与显式 lineage 边界。
- 新增 provenance-assertion/v1 与 parameter-provenance/v1 schema，冻结来源类型、trust、derivation、32 父引用上限；参数绑定不能夹带 caller trust/source_type。
- `internal/provenance` 已提供 Assertion/Scope/Issuer/Constraint 类型、普通客户端上报上限、canonical 内容摘要、严格 JSON Pointer 和约束 taxonomy 校验。
- `go test -race ./internal/provenance` 与 `go vet ./internal/provenance` 通过；覆盖全部来源 × trust 组合、伪造 USER/IAM、空 source identity、非法/歧义 JSON Pointer、数组边界、类型敏感内容摘要。
- Python 新增两项合同测试通过，Ruff 通过；测试明确区分“结构合法”和“签名/授权有效”，不将零签名示例视为运行时证据。
- 本批还未实现 issuer/assertion 持久化、验签、撤销、派生图及 runtime matcher；B1/B2/P01–10 均未宣称完成。下一步接入管理面可信存储，随后实现 Intent V3 和 MCP 流程。

### B1 单节点授权验证增量

- 新增 trusted-source-issuer/v1 合同，要求显式完整 scope、来源许可与可信度上限；外部公钥/local-state 引用二选一。
- Assertion.VerifyAuthority 使用现有 canonical signing 验签，验证 assertion 与 issuer 的结构、来源授权、trust ceiling、完整 scope、双方时效及 revoked_at。支持外部 Ed25519 公钥，不把模型固定为只支持本地密钥。
- `go test -race ./internal/provenance` 与 vet 通过，包含本地/外部正例、14 类篡改/越界/撤销负例和精确到期边界。Python provenance 合同测试现为 3 项，全部通过，Ruff 通过。
- 该 API 只接受管理面已验证的 registry entry，尚未接入 HTTP 或持久化；这里的撤销检查只验证 entry 状态，不代表撤销发布流程已经完成。父节点验签、派生防升级、可信存储与 runtime 接入继续待实现。

### B1 签发者持久化增量

- 新增 provenance.Store：管理身份签名的不可变 issuer record 与绑定原记录摘要的终态撤销 sidecar；同 ID 同内容重试，改内容冲突，撤销后不能重新注册清除状态。
- GetIssuer 每次重新验证记录及撤销签名；拒绝未知字段、多 JSON 文档、超大文件、符号链接和路径穿越。写入 0600 临时文件、fsync、排他硬链接；无覆盖回退。
- `go test -race ./internal/provenance` 和 vet 通过；新增重启/终态撤销/原记录字节不变、16 并发注册读取及撤销、篡改撤销/多文档/符号链接负例。Python provenance 合同测试 4 项与 Ruff 通过。
- 新增 issuer-record/v1 与 issuer-revocation/v1 合同。此批尚未接入管理 HTTP，也未实现 assertion 图存储与 runtime matcher；不把 registry 完成解释为 B1 全部完成。跨进程容量与整目录回滚防护没有超出既有单 daemon/same-UID 边界的保证。

### B1 来源图初步实现

- 新增 IssueAssertion/ImportAssertion/Resolve，按完整 scope 摘要存储不可变声明；发布前验签并递归验证父节点。限制32父节点、64层、1024节点和4096边，拒绝同 ID 内容冲突。
- 父节点 trust 不能被提升；派生 source type 不能将 MCP 伪装成 USER，允许保持类型或降为 AGENT/UNKNOWN；unknown 派生必须保持 unknown trust。子节点到期不能晚于父节点。
- 读取不保留跨请求缓存，父 issuer 撤销影响后续子图解析。目录/记录符号链接、无效签名和缺失父节点失败关闭。
- 已执行 provenance 包 race 测试，覆盖低可信升级、MCP→USER 洗白、同记录重试、重启、跨会话、到期、撤销和深度64通过/65拒绝。后续仍需补混合聚合、节点/边容量边界、并发 issue+resolve+revoke、固定签名向量与 HTTP/runtime 接入；B1 未完成。

### B1/B2 匹配与边界增量

- Store.MatchParameters 在同一读锁内校验全部引用及父图，绑定参数 canonical 内容摘要，随后逐引用应用来源类型、最低可信度和 required 约束。未受约束的伪造引用也不能被静默忽略。
- 实测同一收件人值 USER/authoritative 通过、MCP/untrusted 拒绝；混入 USER 引用不能掩盖 MCP，参数值替换/缺失引用/重复引用均拒绝。此为真实签名 store+matcher 测试，尚非 Decide HTTP 端到端测试。
- 来源图节点1024/1025、边4096/4097边界测试通过；混合父节点保留最低信任，unknown 父节点不能转换成已知 lineage。并发签发/解析通过，撤销完成后所有后续解析拒绝。
- provenance 全包 race（含容量测试）通过；新增聚合/并发及修正 unknown 传播后相关定向 race 通过，vet 通过。容量测试预置有效签名记录以避免测试准备阶段重复执行二次方扫描。
- 尚需固定签名向量、管理/上报 API、Intent V3 和 RuntimeActionDescriptor 高影响参数接入；目标保持进行中。

### B2 V3 决策接入增量

- 新增 intent-contract.v3 schema 和固定 Go 签名样例；V2/V3 双读，V2 不接受新约束字段（包括显式 null），V3 要求显式 provenance_constraints 数组。约束中的 required 缺省/null 不会被静默解释为 false。
- receipt.Request/Receipt 增加参数来源引用；Decide 与 hold-status 使用绑定 Intent 的 scope 验证来源，生产 serve 已配置 Store.MatchParameters。V3 缺检查器硬拒绝；V2 无新引用保持兼容。
- 真实签名 Store→Intent V3→Engine 测试覆盖三模式下 USER 同值允许、MCP 同值拒绝、缺必需来源拒绝；暂无管理/上报 HTTP 端到端证据。
- Go 全模块 race、vet、四平台编译通过；随后 V2 null 字段拒绝加强，相关 intent/receipt/server 定向 race 重新验证。Python Intent/receipt 合同测试126项通过，Ruff通过；Web build通过。
- R 中高影响参数自动约束覆盖、HTTP 发行/上报、MCP 生命周期及更多审批 provenance 失效测试继续待完成；不宣称本轮45项DoD已完成。

### B1/B2 管理 API 增量

- 接入 issuer 注册/读取/撤销、声明本地签发/外部导入/当前父图解析六类管理操作；统一 admin capability、严格64 KiB JSON读取、稳定错误码，生产 Server 与 Engine 共享状态目录。
- 原始 HTTP 请求验证 decision token 对所有管理路径的 GET/POST 均403，不使用会自动替换 admin token 的旧测试辅助行为。
- 新增管理注册→V3绑定→声明签发/导入/解析→Decide→撤销→后续Decide硬拒绝链路测试。warn 正例只证明有效 Authority 进入既有 advisory policy，不作为 Grant 或真实效果证据。
- ParameterBinding 的 JSON 边界拒绝多文档、未知字段、空/重复/非法引用和非法 JSON Pointer，避免恶意绑定生成不符合合同的回执。
- server/receipt/provenance 三包 race 全部通过，server/provenance vet通过，四平台编译通过。使用说明见 [Provenance API V1](provenance-api-v1.md)。普通低可信上报与 MCP 路径仍待实现。

### B1 受限上报增量

- 新增 decision capability 的 `/v1/provenance-reports` 和请求合同；Scope 的 task_id 来自有效 Intent，客户端不得自选 issuer/task/signature，source/trust 有独立硬上限。
- 专用 scope report issuer 仅允许五类低可信来源，内容与来源标识都只存摘要；声明最长15分钟且不超出 Intent，scope+report_id 幂等且过期不自动续期。
- 全流程串行化 registry/声明写入，16并发重复上报得到同一签名。测试验证伪造 USER/IAM/高可信 MCP 拒绝、同 ID 内容冲突、过期拒绝、磁盘无原始内容，以及 HTTP 自报权限边界。
- 新增 provenance/server 定向 race 与 vet 通过，Python provenance 合同测试5项与 Ruff通过。上报仍为 self-reported 输入；实际 MCP 调用、endpoint/tool 身份与确定性派生接入继续待完成。

### B2 确定性选择增量

- Store.Select 与 decision `/v1/provenance-select` 已接入：原始完整 JSON 与父节点内容摘要匹配后由服务提取字段，子摘要绑定结果并保留父引用、来源/trust/时效；不能自报输出值或升级 USER/IAM。
- 真实签名 Report→Select→MatchParameters 测试验证 MCP 选择仍不能通过 USER/trusted 约束，显式允许 MCP/untrusted 的约束通过。覆盖原文替换、字段缺失、幂等选择、撤销父节点拒绝。
- provenance/server 定向 race通过，provenance vet通过，Python 合同测试6项与 Ruff通过。选择请求合同和使用说明已落盘。
- 本轮只完成确定性派生机制，尚未实际调用 MCP server；真实 transport、endpoint/tool identity 采集与 native 平台接入继续待完成。

### B2 MCP 协议组件验收

- 新增 `scripts/validate-mcp-provenance.py`，启动隔离 loopback MCP JSON-RPC server，实际执行 initialize/initialized/tools-call；采集 endpoint/serverInfo/tool 身份摘要与真实 HTTP 返回的 structuredContent。
- 复用已有临时 Harness，以生产 Go daemon 完成准入、Grant challenge/approve/deploy、V3绑定、Report→Select→Decide。MCP 控制路径拒绝；同值 USER/authoritative 来源允许。不是依靠 warn 放行的正例，daemon 使用 block。
- 实际运行成功，2条回执由离线 CLI 验证签名链；Ruff通过。[验收报告](evidence/provenance-v1/mcp-component-20260908.json) 记录源码基线、二进制/脚本哈希与身份摘要，无凭据和原始工具内容。
- 此项覆盖 component_fixture 和固定 HTTP JSON 分支，不声称完整 MCP/SSE/OAuth 客户端或 native 平台支持；生产适配器自动采集、R高影响默认约束与后续 EffectEvidence/Benchmark 仍待完成。

### R/B2 高影响参数默认约束验收

- V3 中未被显式签名约束覆盖的高影响 JSON Pointer，默认 required=true、minimum_trust=trusted，仅接受 USER/SYSTEM/TRUSTED_IAM/TRUSTED_DATABASE。显式约束按路径覆盖默认项，允许管理员有意识地授权低可信来源；V2 行为不变。
- Provenance 直接消费 RuntimeActionDescriptor 的 HighImpactParameterPaths，完成第六类消费者接入；临时补全约束不修改签名 Intent。
- 修复前实际运行 `TestV3DecisionUsesSignedParameterProvenance/block/default` 失败：空 constraints 的 V3 允许 MCP 控制文件路径。修复后 explicit/default × block/warn/audit 六组均通过，同值可信来源允许、不可信或缺失来源拒绝。
- `go test -race ./...`、`go vet ./...` 与 linux/amd64、linux/arm64、darwin/arm64、windows/amd64 编译通过。另有12类高影响参数和显式覆盖回归测试通过。
- MCP 组件重新执行通过，2条回执离线验签成功；临时报告 `/tmp/siq-mcp-defaults-validation.json`，二进制 SHA256 `e6339c3ebad64c1858909d2ca4051d184f7dd4db0e69145f5dc43caedff7ad8d`。该报告基于 e1f4093 加本次工作树修改，不将其标记为该提交的干净构建。
- C EffectEvidence/Completion、D Benchmark、G 门禁及完整45项验收仍待开发。

### C1 合同起步

- 新增 ADR-0017 与 effect-evidence/v1 schema，冻结多维证据、动作/决策引用与签名字段；tool_report/unknown 不能伪造独立性、完整覆盖或预期结果。
- Python 合同3项与 Ruff通过；初次测试发现环境未安装 jsonschema 可选 date-time 校验器，补充时间字符串结构 pattern，运行时仍须严格解析有效时间。
- 本批仅定义合同，尚未实现 observer capability、效果存储/API、关联校验或 Completion；示例零签名只用于结构测试。

### C1 签名模型增量

- `internal/effectevidence` 实现 Evidence/Source、64 KiB 严格单文档读取、结构/时间校验及现有 signing/canon 验签。拒绝未来或无效日期、自报独立性/覆盖/结果升级和明文资源引用。
- 资源引用统一为 `<domain>:sha256:<digest>`，直接消费 RuntimeAction ResourceRefs；不重复归一化、不持久化路径/URL/收件人原文。
- 新增 Python/Go 共享签名样例，Go 验证 Python 固定 seed 样例并断言同签名；覆盖 action/receipt/source/resource/coverage/result/digest 篡改拒绝。
- Python 合同4项和 Ruff通过；Go effectevidence 定向及全模块 race/vet、四平台编译通过（日志 `/tmp/siq-effect-model-race.log`）。该包仅验证记录完整性，尚不能证明提交者具备 observer 权限、记录关联真实动作或任务完成；这些验收项继续待实现。

### C1 真实动作关联增量

- Engine.EffectAction 从已签发/恢复动作状态获取精确 action_id+receipt_id 的最小投影，资源与效果切片复制，caller 不可改写缓存；未知、错配和24小时关联窗口到期拒绝。被拒绝动作仍可读取以接收独立越权事件。
- Correlate 要求受信 observer Source 完全一致且观察时间不早于决策；独立 completed + 未授权动作产生 unexpected/unauthorized_effect_observed，效果或资源错配产生 unexpected/effect_scope_mismatch，自报不生成独立事件。
- effectevidence/receipt 全包 race通过，包含伪造 action/receipt/source/type/independence、时间错配、资源错配、重启、hold 审批恢复和缓存不可变测试。
- Go 全模块 race、vet 和四平台交叉编译通过，日志 `/tmp/siq-effect-correlation-race.log`。
- 本批为运行时关联基础，尚未开放 EffectEvidence HTTP API；独立 capability、证据与 finding 原子持久化、observer、Completion 继续待实现。24小时窗口用于新提交关联，不代表历史任务已完成或历史证据可被忽略。

### C1/C2 不可变存储增量

- 新增 effect-evidence-record/v1，外层签名绑定 Evidence、finding_code、原请求摘要与 task_id；内部 Evidence 仍可按独立合同验签。证据和事件分类通过单文件排他发布，不存在二者分别写入的中间状态。
- Store.Submit/Get 实现先关联再签发、16并发跨 Store 幂等、原始请求摘要冲突校验、重启读取及内外签名验证。动作后来变为允许不会将已记录的 unauthorized_effect_observed 改为成功。
- 覆盖事件字段篡改、路径穿越、符号链接拒绝、不完整暂存文件不可读、8192容量边界。容量保守计算目录全部条目，残留暂存文件不会变为有效证据，但会占用预算。
- effectevidence 及全模块 race、全模块 vet、四平台编译、Python合同5项和Ruff通过；Go日志 `/tmp/siq-effect-store-race.log`。HTTP/API capability、按动作查询、文件/网络 observer、Completion 仍未接入，不将存储单测视为端到端验收。

### C1 observer capability 与 HTTP 增量

- 新增 capEffectObserve，管理端短期签发/撤销、完整任务 scope 和固定 Source、token 摘要内存存储、到期与重启失效。提交和撤销共享锁；普通 decision/admin 不能充当 observer。
- 接入生产 Server：POST effect-evidence、admin GET 单记录/按动作查询；来源权限→真实动作 scope→分类→原子签名存储。接口说明见 [EffectEvidence API](effect-evidence-api-v1.md)。
- 原始 HTTP 验收验证决策 token 管理拒绝、decision/admin 提交拒绝、来源冒充、错配回执、跨任务、撤销/过期、重启 token 失效与记录保留；测试 observer 提交被拒绝动作效果，实际保存 unauthorized_effect_observed 并读回。
- Go 全模块 race/vet、四平台编译通过，新增重启断言后 HTTP 定向 race 通过；Python 合同6项与Ruff通过。日志 `/tmp/siq-effect-http-race.log`。
- 尚未接入实际文件/网络 observer、Completion；查询暂为8192条有界验签扫描，分页与性能基线待完善。

### C1 文件观察基础实现

- 提取 ADR-013 既有文件打开逻辑为 internal/fileopen，准入扫描保留原入口与行为。Unix NOFOLLOW/NONBLOCK 与非 Unix 回退未新增平台假设。
- CaptureFile 实际读取目标前后状态，输出存在性/内容摘要/size/mtime/采样时间与统一资源摘要；拒绝可见符号链接（含父目录）、非普通文件、超限及检测到的读取期间变化，最大16 MiB。
- FileWrite 将实际变化+预期摘要匹配分类为 completed/expected；文件缺失为 failed/unexpected，内容不符为 unexpected，无可见变化为 unknown。生成 host_independent/partial Evidence，可进入既有签名存储。
- 使用真实临时文件验证写入、假成功（无文件）、同值无变化、内容不符、上限/超限、符号链接、反向时间和拒绝动作产生实际效果后的事件分类。观察对象不含路径或内容原文；admission/effectevidence race通过。
- Go 全模块 race、vet 与四平台编译通过，日志 `/tmp/siq-file-observer-race.log`。
- 本批提供观察库，尚未完成 CLI/HTTP observer 生命周期及观测材料持久化引用；不能宣称用户安装后已自动观察文件。Windows 原生路径语义仍未支持，四平台编译不代表 Windows 实机观察验收。

### C1 文件观测材料持久化

- 新增 file-observation/v1 元数据合同，Record 可选 file_observation 与证据/事件共同签名；旧无材料记录省略新字段，保持原签名表示。
- SubmitFile 保留前后存在性、摘要、size、mtime、采样时间及预期摘要；读回重新派生 evidence_digest 并验证资源、时间、效果和执行状态关联。材料不含原始路径/文件内容。
- 实测真实文件材料提交、幂等重试、读回、拒绝将带材料记录降级为普通摘要提交，以及外层重新签名后仍拒绝与原效果摘要不匹配的材料。
- effectevidence 及全模块 race/vet、四平台编译、Python合同7项与Ruff通过；日志 `/tmp/siq-file-material-race.log`。API 使用流程尚未接入 SubmitFile，后续仍需可信 observer 采样生命周期、网络 oracle、Completion 和完整验收。

### C1 文件采样 HTTP 接入

- 新增 observer begin/finish 两阶段 API，服务实际采样，不接受客户端自报快照；验证固定 host 来源、scope、真实 file.write 动作及路径资源摘要。
- pending 只存摘要/元数据，128上限、token 归属及到期；完成重试返回原持久化证据，避免重采样改写。已撤销 observer 的 pending 在后续 begin 清理。
- 原始 HTTP + 真实临时文件验证路径替换、伪造 before/after、决策 token 拒绝、真实写入、缺失文件假成功和完成重试。block 用例产生拒绝后实际效果事件；warn 正例遵循 advisory policy，不冒充 block Grant 准入通过。
- Python合同8项与Ruff通过；HTTP定向及Go全模块race/vet、四平台编译通过，日志 `/tmp/siq-file-http-race.log`。跨重启 pending 恢复、实际平台采样调度、网络 oracle、Completion 与完整验收仍待完成。

### C1 受控网络 oracle 基础

- NetworkOracle 启动真正的127.0.0.1随机端口 HTTP server，随机私有接收路径；只从服务器实际接收事件生成证据。scheme/host/port/resolved_target来自监听配置，不由请求 Host 头决定。
- 服务器 request_id、接收时间及请求组合摘要可供复核；不保留正文、URI或伪造 Host。1 MiB正文和64事件预算，超限不生成完整事件。
- 实际 HTTP 测试验证：未收到请求时无证据、直接接收、服务器事件不可被调用方修改、localhost批准目标→302→127.0.0.1最终目标差异、资源错配和拒绝动作效果事件。网络 Evidence 进入既有签名 Store。
- effectevidence 定向及Go全模块race/vet、四平台编译通过，日志 `/tmp/siq-network-oracle-race.log`；此为受控本地测试 oracle，不声称互联网/provider/native平台支持。网络原始事件材料的签名归档、benchmark编排及 Completion 继续待开发。

### C2 签名效果要求起步

- Intent V3 可选 effect_requirements 纳入同一 canonical digest/签名，先支持 file.write 的资源摘要、预期内容摘要、最低独立性/覆盖要求。缺省/空数组不表示完成；V2拒绝新字段，V3显式null拒绝，旧V3固定签名样例保持一致。
- 运行时验证字段完整、最多128项、ID唯一、效果在 allowed_effects 中。改变同一 Intent 的预期内容摘要会改变签名摘要，要求不会作为额外动作授权来源。
- intent/completion 定向及Go全模块race/vet、四平台编译通过，Python合同9项及Ruff通过；日志 `/tmp/siq-completion-intent-race.log`。当前仅完成可信要求模型；状态聚合、任务查询 API 及网络完成要求尚未实现。

### C2 确定性 Completion 聚合

- 新增 completion.Evaluate，对 Record 内外签名及材料复验；Engine 动作投影补齐 Intent ID/digest，确保 task/Intent/action/receipt 关联一致。
- 每项要求检查实际文件后摘要、签名预期摘要、独立性、coverage、执行状态、授权/资源/效果匹配；无证据 incomplete，无要求 unknown/not_required，弱或无材料证据 unknown，冲突/安全事件 conflicting，全项满足才 verified。
- 真实文件→采样→SubmitFile签名记录→聚合测试通过，覆盖预期内容替换、full/external更高要求、正例混入无材料证据、外层篡改、Intent错配、重复证据和安全事件不能被正例遮蔽。
- completion/effectevidence/receipt 三包及Go全模块race/vet、四平台编译通过，日志 `/tmp/siq-completion-aggregate-race.log`；任务HTTP查询、历史动作超24小时恢复及网络完成要求仍待接入，聚合器不等于完整业务工作流。

### C2 Completion HTTP 接入

- Admin GET tasks/{id}/completion 已接入生产 Server，验证 Intent 与按task完整验签的证据集合，再调用 Engine 关联和 Completion 聚合。不缓存；无任务404、Intent归属歧义409、损坏/不可关联状态500，客户端不能POST completed。
- 文件HTTP fixture 升级为真实签名 V3 效果要求，显式将 /path provenance 设为可选以隔离效果验收；验证无证据incomplete→服务端实际采样材料→warn正例verified，以及新增缺文件失败后incomplete。block继续验证越权效果conflicting。
- 旧无要求Intent返回unknown/not_required；原始HTTP验证decision token拒绝、写状态拒绝、未知任务与歧义处理。warn正例仍不冒充block Grant完整准入。
- HTTP定向及Go全模块race/vet、四平台编译、Python合同10项与Ruff通过，日志 `/tmp/siq-completion-http-race.log`。历史动作恢复、pending恢复、网络材料/完成、benchmark与最终门禁仍待开发。

### C2 历史动作查询恢复

- Completion 改用 HistoricalEffectActions，按本次记录引用单次验签扫描历史回执链，恢复精确决策及关联审批结果，不依赖24小时缓存、不重新注册执行权限。
- 覆盖48小时后重启历史读取、批准/拒绝hold恢复、投影切片不可变、伪造引用、回执篡改和运行中删去有效链尾拒绝；新 EffectAction 提交仍在到期后拒绝。
- HTTP Completion/文件采样定向及Go全模块race/vet、四平台编译通过，日志 `/tmp/siq-effect-history-race.log`。历史复核以当前进程已知链头检测截断，完整状态回滚后重启仍依赖已有可信checkpoint，不宣称永久防回滚。
- 后续还需加强审批生效时间与 observed_at 的先后关系：当前投影保留批准状态，尚未提供独立批准时刻。另有 pending 持久恢复、网络归档与benchmark待完成。

### C2 审批时间边界修复

- 修复前 `TestApprovalCannotRetroactivelyAuthorizeEffect` 实际失败：同一秒内07:00:00.103的效果，在约07:00:00.503审批后被接受为expected。
- 当前动作、重启恢复、历史查询新增来自签名审批回执的AuthorizedAt；新hold_resolution使用RFC3339Nano。Correlate将审批前独立completed效果归为unauthorized_effect_observed；Completion也校验时间关系，防止旧expected记录被后续审批追认为成功。
- 验证前置效果拒绝、审批时刻边界允许、当前/重启/历史投影时间一致，以及Completion的审批前记录conflicting。旧秒级审批只保留原有时间精度，不能恢复未记录的亚秒先后；该历史精度限制仍须在最终报告说明。

- 本批Go全模块race、vet与四平台编译通过，日志 `/tmp/siq-effect-approval-time-race.log`。pending恢复、网络材料归档和benchmark等工作继续进行。

### C1 网络材料签名归档

- NetworkOracle.Material 从本服务器已接收事件生成只含端点/接收元数据的材料；新增 network-observation/v1 与 Record 可选 network_observation，和文件材料互斥。
- SubmitNetwork 将材料、效果、事件同封套签名；读回重新派生摘要、最终资源、接收时间和执行状态，普通摘要提交不能覆盖带材料记录。Source identity 与 server request_id 的完整前缀一致。
- 实际HTTP oracle 测试覆盖材料保存/读回/幂等、去材料重试拒绝、外层重签后端口替换仍不能绑定原内层摘要；原有直接接收、重定向、预算和隐私测试继续通过。
- Go全模块race/vet与四平台编译通过（`/tmp/siq-network-material-race.log`）；随后来源ID精确匹配加强，network定向race/vet复验通过。Python合同11项与Ruff通过。网络材料HTTP提交、网络Completion及benchmark编排仍待接入。

### C1 网络材料 HTTP 接入

- 实现 POST /v1/network-observations，observer capability 与固定 test_oracle/external_independent 来源、真实动作 scope 绑定；正文不允许自报授权、来源或 scope。
- 实际 loopback HTTP 收到请求后生成材料，经 observer API 提交并签名保存。覆盖 decision/admin token 拒绝、方法/未知字段拒绝、伪造回执与服务器 request_id、跨任务凭据拒绝、同内容幂等、不同材料冲突、撤销后拒绝和重启后签名材料读取。
- block 拒绝动作后实际收到测试请求，归档 unauthorized_effect_observed；该用例验证越权效果检测，不作为正常 Grant 放行链路。接收端来源由管理员信任配置，不声称能辨别持有受信 observer 凭据的恶意上报者。
- Go 全模块 race、vet、linux/amd64、linux/arm64、darwin/arm64、windows/amd64 编译通过，日志 /tmp/siq-network-http-race.log；Python 效果合同12项与Ruff通过。测试准备中修正了非法材料400预期和重启管理凭据不复用的断言，未放宽生产校验。
- 网络 Completion 要求、pending持久恢复、平台采集、D基准与G最终验收仍待完成。

### C2 网络效果完成要求

- 签名要求增加 network.request、expected_endpoint（scheme/规范化host/port）与预期请求组合摘要；网络要求必须external_independent，host与resource摘要一致，文件要求不接受网络字段，旧文件签名省略新字段保持兼容。
- Completion 验证已签名材料的 requested/received 两端与预期端点及请求摘要一致；无材料unknown，端口/协议/摘要不同conflicting。真实loopback接收→签名Store→聚合正例verified；无证据incomplete、更高full覆盖unknown。
- Go completion/intent定向race及全模块race、vet、四平台编译通过（/tmp/siq-network-completion-race.log）；Python合同13项通过。网络要求的完整Intent签发→HTTP Completion正例及平台编排仍待补齐，不将库级材料测试称为完整端到端验收。
- pending持久恢复、D独立基准、平台自动采集及G最终门禁仍未完成。

### C2 网络 Completion HTTP 验证

- 补齐管理员签发 V3 网络要求→绑定→Decide→真实 loopback GET→observer 材料提交→任务 Completion 查询。预期请求摘要在发送前计算并签发，不从已发生事件倒填预期。
- warn 普通策略用例从 incomplete 变为 verified；block 拒绝后真实效果返回 conflicting。同一 Intent ID 修改 expected_endpoint 再提交409，原任务完成结果保持不变。
- Go server 定向race、全模块race与vet通过（/tmp/siq-network-completion-http-race.log）。此为生产HTTP handler与真实网络oracle的集成测试；显式可选 /url provenance 隔离效果检查，warn正例不代替block Grant链路，不声称native平台自动调度已经完成。
- 后续重点仍为pending恢复、独立D0–D5基准、平台集成及G全仓验收。

### D 基准合同与统计起步

- 新增 benchmarks/runtime-security/scenario.schema.json，规定攻击/正常对照、pair/category/fixture/task及D0–D5显式预期，覆盖模板18类攻击并预留内容篡改、审批先后两类。
- 新增 metrics.py，对runner实际观测按攻击/正常与阶段分别统计；null保留not_evaluated，D5声明缺独立来源/已验证材料时拒绝，零分母rate为null。分阶段真实耗时用nearest-rank P50/P95/P99，不填造缺失数据。
- 4项统计单测、Ruff、schema合法性及正负样例校验通过。统计输入的材料验证标志必须由可信runner产生，该模块本身不验签、不接受外部布尔值作为效果证明。
- 尚缺20对实际场景、真实运行时执行器、全部命名指标映射、阶段埋点、CI smoke/nightly与运行报告；D仅开始，未宣称验收通过。

### D 首组真实运行时基准

- 新增mcp_parameter_control攻击/正常两个场景与run.py执行器，复用隔离Harness实际构建daemon、准入并部署Grant、MCP HTTP调用、签名来源和V3决策，停服后离线验签回执链。
- 场景预期与实际决策reason_code、阶段值分别保存并比较；实际MCP路径控制deny，可信USER同值allow。目标工具没有执行，D3–D5均not_evaluated，不能从allow推导执行，也不能从deny推导独立无效果。
- 真实执行报告 /tmp/siq-runtime-benchmark-first-pair.json（09b5452加本轮工作树），两条回执验证通过；攻击/正常各D2分母1、D5分母0。场景schema验证、4项统计测试、Ruff通过。
- 当前仅1对组件场景；其余至少19对、D3–D5真实材料、全部指标、阶段埋点及CI仍待完成。未把现有unit test汇总冒充独立benchmark。

### D 来源攻击扩展为4对

- 可选extended执行模式增加来源缺失、内容替换、跨会话重放；每类单独发起可信USER正常请求作为对照，避免只重复检查先前allow结果。原MCP组件脚本默认仍运行原始一对。
- 实际生产daemon返回 provenance_missing、provenance_content_mismatch、provenance_not_found，对应正常请求全部allow；跨会话场景先在另一会话合法绑定同Intent，确保拒绝来自来源引用隔离而非缺Intent绑定。
- 4对共8条回执离线验签通过，报告 /tmp/siq-runtime-benchmark-four-pairs.json（a9ff866加本轮工作树）。全部8个场景schema与成对关系验证、4项统计测试、Ruff通过。
- 此批D2计数真实，D3–D5仍未评估。至少20对、效果oracle、完整指标、埋点和CI仍待完成。

### D 跨任务与绑定撤销，累计6对

- 新增wrong-task：来源签名与请求会话、参数摘要一致，仅来源task与当前Intent task不同，实际provenance_not_found拒绝，排除跨会话不匹配掩盖任务边界的情况。
- 新增revoked-binding：先对新合法绑定与匹配来源实际Decide allow，再通过管理API撤销绑定，后续intent_binding_revoked拒绝；原有效绑定正常对照仍allow。此处是绑定撤销，不宣称全局Intent撤销。
- 真实报告 /tmp/siq-runtime-benchmark-six-pairs.json（146b0bb加本轮工作树），12个基准观测及额外撤销前探针回执全部离线验签；6对schema/成对关系、分母检查、4项统计测试、Ruff通过。D5仍为0分母。
- 尚需至少14对、真实效果阶段与独立oracle、性能埋点和CI；全局撤销语义与完整DoD继续按实际功能核对。

### D 首组D3–D5文件效果基准，累计7对

- 新增独立effect_fixture：真实block daemon准入、Grant批准部署、V3效果要求签发和Decide allow后运行受控fixture工具；攻击返回success但不写，正常分支实际写文件。
- 服务端observer真实前后采样、签名材料归档、GET复验与Completion历史动作复核；攻击incomplete且实际文件不存在，正常verified。D5数据来自host_independent/partial材料，不是模型或工具返回值。
- /tmp/siq-runtime-benchmark-seven-pairs.json实际运行成功（07f325f加工作树），14个基准观测；每组D5分母1、其余6条排除。全部场景schema校验、4项统计测试、Ruff通过。两套daemon各自回执链离线验签通过。
- 仍待至少13对、其他效果攻击/外部oracle、全部命名指标、性能埋点和CI；host observer不代表OS隔离。报告中fixture临时状态在结束后清理，最终长期可独立复验的证据包仍需完善。

### D 越权效果与冲突内容，累计9对

- 新增denied-effect：真实Intent工具约束拒绝后，受控fixture模拟绕过deny写入临时文件，observer归档unauthorized_effect_observed、Completion conflicting。正常对照同Grant且Intent允许，实际写入verified。
- 新增conflicting-effect：动作合法但fixture写入与签名expected_digest不符的内容，实际采样后Completion conflicting；正常对照verified。D4/D5表示实际文件效果发生，不把存在文件等同正确完成。
- 实际执行 /tmp/siq-runtime-benchmark-nine-pairs.json（92c4427加本轮工作树）通过，两套daemon各自链验签成功；18个观测，每组D5分母3、未评估6。9对schema/成对关系与报告断言、4项统计测试、Ruff通过。
- 仍待至少11对、外部网络oracle基准、全指标与阶段埋点、CI及其他工作包验收。未把新组件测试视为native适配器强制执行证明。

### D 命名指标与显式决策预期

- 场景增加expected.decision_action；runner分别比较实际action/reason/stages，假成功和内容冲突的合法动作预期仍为allow，不能仅因attack标签计成误放行。
- 输出9项命名指标的numerator/denominator/rate，并按attack/benign分组；缺效果证据不进入效果率，缺Completion不进入正常完成率，空分母null。D0–D5阶段计数继续单独保留；命名指标按每阶段完整映射仍须后续补齐。
- 实际9对执行通过，报告 /tmp/siq-runtime-benchmark-metrics.json（d6a57b7加工作树）：误放行0/7、误拒绝0/11、正常完成3/3；资源劫持分母0未评估。越权效果1/6来自刻意模拟deny后绕过的fixture，不描述为已被执行层阻断。
- 6项统计测试覆盖合法攻击动作、预期分类与实际拒绝区别、缺证据/未知证据分母；Ruff通过。报告仅当前组件样本，不能外推生产准确率，未完成完整benchmark目标。

### D 资源边界与真实到期，累计11对

- filesystem-hijack使用当前scope有效USER签名且内容摘要匹配company-b路径，Grant允许workspace而Intent只允许company-a，实际intent_resource_not_allowed拒绝；正常路径allow。排除因伪造/缺来源掩盖资源边界的假阳性。
- expired-provenance先签发短期有效声明并实际Decide allow，等待3.1秒真实到期后同声明provenance_expired拒绝；未到期来源正常对照仍allow，不修改daemon时间或持久化状态。
- /tmp/siq-runtime-benchmark-eleven-pairs.json真实运行通过（d6a57b7之后当前b3445ad工作树增量），22个观测和额外前置探针均经过各daemon回执链验签；11对schema/成对关系、6项统计测试及Ruff通过。资源劫持指标现1/1，D5每组仍分母3、未评估8。
- 至少9对、外部网络oracle、阶段埋点、长期可复验证据与CI等仍待补齐；不按场景数量宣称整体目标完成。

### D 伪造cwd与独立无效果检查，累计12对

- forged-cwd为目标临时目录签发有效Intent与效果要求，但目录在部署Grant workspace外；请求自报context.cwd指向目录，真实block决定grant_scope_violation，避免Intent范围先拒绝而掩盖Grant测试。
- fixture遵守deny不调用工具，observer实际前后采样不存在文件，D3/D4/D5 false；对照在Grant内真实写入、Completion verified。D5 false来自完成的采样，非由deny直接推断。
- /tmp/siq-runtime-benchmark-twelve-pairs.json实际运行通过（93dfaca加工作树），24个观测，两个daemon各自回执链验签成功。每组D5分母4、未评估8；12对schema/成对关系、6项统计测试和Ruff通过。
- 尚需至少8对、网络独立oracle、其他权限伪造/容量场景、长期证据包、性能埋点和CI；完整开发目标继续进行。

### D 真实HTTP重定向与网络材料，累计13对

- 新增network_fixture，第三套隔离daemon实际准入、Grant批准部署（显式localhost/127.0.0.1）、V3网络要求签发、block Decide allow，再发真实HTTP。初始端点的scheme/host/port及请求摘要在请求前签发。
- 攻击服务器302到另一主机和端口，接收handler按监听配置记录最终端点/request_id/digest/time；observer提交签名归档、GET复验、Completion conflicting。直连正常对照verified。没有把请求Host或工具返回当服务器接收事件。
- /tmp/siq-runtime-benchmark-thirteen-pairs.json运行通过（7d72d67加工作树），26个观测，三套daemon链分别离线验签。13对schema/配对、网络材料与分母检查、6项统计测试和Ruff通过；每组D5分母5、未评估8。
- test_oracle为受控loopback接收端，不声称公网provider/OS隔离/native逐跳强制执行。至少7对、剩余权限伪造/容量/审批场景、持久恢复、性能与CI等仍待完成。

### D 请求前目标主机注入，累计14对

- destination-host在Decide之前替换为另一个Grant允许但Intent不允许的主机，实际intent_resource_not_allowed拒绝，fixture不发请求。与http-redirect的批准后目标变化分开测试，正常端点实际接收且Completion verified。
- 拒绝样本D3 false，但没有签名网络absence-event材料，D4/D5保留not_evaluated；检查无服务器事件不能冒充已完成独立效果材料验收。
- /tmp/siq-runtime-benchmark-fourteen-pairs.json真实运行通过（3e4c67d加工作树），28个观测、三套daemon回执链验签。14对schema/配对、6项统计测试、Ruff通过；攻击D5分母5，正常分母6，分别保留未评估数。
- 至少6对及权限伪造/容量/审批、性能、CI、pending恢复等工作仍未完成，完整目标继续。

### D USER/IAM来源伪造，累计16对

- forged-user与forged-iam使用普通decision capability自报authoritative身份，真实API均400/provenance_authority_invalid；按实际report ID计算规则引用被拒绝声明，Decide provenance_not_found拒绝，证明没有铸造可用来源。
- 两个正常对照分别admin注册USER/TRUSTED_IAM issuer并签发同内容来源，独立签名Intent要求对应类型，实际allow。上报拒绝与runtime拒绝单独记录，不把缺来源单测冒充来源伪造链路。
- /tmp/siq-runtime-benchmark-sixteen-pairs.json重跑通过（ce07d5a加工作树），32个观测及额外上报拒绝/前置探针，三套daemon链分别验签。16对schema/配对、6项统计测试、Ruff通过。
- 仍需至少4对、recipient/容量/审批相关场景、完整阶段指标/性能、可离线复验证据包、恢复和CI等，未达到最终DoD。

### D 消息收件人来源约束，累计17对

- 独立recipient_fixture配置真实send_message Grant和Intent message资源、/recipient required USER约束，同值MCP低可信report拒绝provenance_source_not_allowed，合法USER声明allow。
- 不借read_file无关参数充数；实际RuntimeActionDescriptor按message.send提取recipient。没有真实消息发送，D3–D5未评估，也不把受限report称为实际MCP地址簿调用。
- /tmp/siq-runtime-benchmark-seventeen-pairs.json运行通过（61311cb加工作树），34个观测，四套daemon各自回执链验签；17对schema/配对、6项统计测试和Ruff通过。
- 尚需容量、审批撤销和至少20对要求，以及完整证据包、性能埋点、CI与pending恢复等任务；整体目标未完成。

### D 真实签名来源图深度预算，累计18对

- 生产API连续签发64层USER transformed链，第65层503/provenance_capacity；没有绕过签名或直接写入状态目录。随后超限节点引用deny，已有64层链仍allow。
- capacity_checks单独记录实际签发成功/拒绝边界；正常对照在超限尝试后执行，证明失败未破坏有效图。该对是深度预算，节点1024/边4096/并发容量基准仍需后续覆盖。
- /tmp/siq-runtime-benchmark-eighteen-pairs.json真实运行通过（4e1d3c1加工作树），36个观测，各daemon链验签；18对schema/配对、6项统计测试、Ruff通过。
- 至少20对门槛及审批撤销场景尚未满足；持久恢复、平台集成、性能、完整证据包与CI同样仍在目标内。

### D 审批后执行前Grant撤销，累计19对

- 新增approval_fixture，真实部署OpenClaw require_approval Grant，Decide hold后admin批准并先读取approved；攻击随后撤销Grant，执行前hold-status变denied，受控marker工具不执行；正常对照执行。
- 使用optional/unbound兼容路径，不执行command字符串，也不放宽required opaque shell。此为HTTP组件审批门禁，native平台完整验收仍待最终回归；marker未进入独立效果归档，D4/D5不计。
- /tmp/siq-runtime-benchmark-nineteen-pairs.json真实运行通过（c6dffe3加工作树），38个观测，五套daemon链各自验签。19对schema/配对、审批状态与执行断言、6项统计测试及Ruff通过。
- 至少20对门槛尚缺一对；签名证据导出、全阶段指标/性能、pending恢复、平台集成及CI等大量工作仍在完整目标内。

### D 审批后参数替换，达到20对组件场景

- 新增approval-params：真实hold获批并复查approved后更改params，执行前hold-status以400/hold_identity_mismatch拒绝，受控工具不执行；正常对照参数保持一致并执行marker。
- /tmp/siq-runtime-benchmark-twenty-pairs.json真实运行通过（7d95f72加工作树），40个基准观测、五套daemon回执链各自离线验签。20对schema/配对、参数绑定断言、6项统计测试及Ruff通过。
- 仅达到20对数量门槛，不代表D或全目标完成：D0/D1未评估，多数D3–D5仍缺独立材料，容量仅深度边界，命名指标全阶段映射/性能埋点/长期证据包/CI待完成。全局Intent撤销不能由绑定撤销冒充，native平台验收与pending恢复同样继续待开发。
