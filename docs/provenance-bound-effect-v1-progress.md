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
| C2 | 幂等/冲突/越权效果事件、CompletionStatus、恢复 | Completion API、历史动作与审批时间复核已实现；pending签名持久化、admin接管及双SIGKILL恢复通过；完整故障矩阵/平台调度待完成 |
| D | 独立 benchmark，至少20场景、攻击对应 benign、D0–D5 分母与阶段性能 | 21对组件场景与八阶段性能基线通过；完整语义证据包及远端CI待完成 |
| G | ADR 15–17、威胁27–35、能力矩阵、README、CODEOWNERS、CI smoke/nightly | ADR/API、T27–T35、能力矩阵、CODEOWNERS及CI工作流已更新；README与最终报告待整体验收 |
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

### D 公共回执证据导出与独立验签起步

- runner在临时状态清理前按receipts/*.jsonl白名单导出五套daemon公钥/二进制摘要/完整回执，不复制seed、token或整个状态目录。效果签名封套继续随观测保存。
- 新增独立Python evidence.py，验回执序号/prev_hash/content hash/Ed25519、效果内外签名及动作关联，拒绝缺链。发现并兼容Go Record.unsigned的数字float64表示（size 28.0），没有改写历史签名。
- 20对真实重跑报告 /tmp/siq-runtime-benchmark-public-evidence.json（2a21217加工作树）；daemon清理后Python独立验证46条回执、11个效果封套通过。实际报告篡改回执、篡改效果、移除链三种负例全部拒绝，Ruff通过。
- 目前只证明签名/关联一致性；外部信任锚、完整性checkpoint、Intent/来源图归档及Completion离线语义重放尚待补齐，不能把自包含公钥当作外部可信证明。性能/CI/pending恢复等仍未完成。

### D 离线报告一致性与可选外部摘要锚

- evidence.py将每个D2观测关联到签名decision的action/reason，核对完整reviewed场景集/摘要/预期；缺失、重复或未知观测拒绝。重新计算命名指标与阶段统计，拒绝手工改结论。
- D5的独立性和文件存在性/网络材料必须与已签名封套一致；增加--expected-sha256用于调用者提供独立可信报告摘要，检测整包替换。不把报告自带公钥或同源摘要当外部信任锚。
- 既有真实报告46回执/11效果离线复验通过；篡改action、指标、删样本、重复样本、提高独立性、翻转D5六类实际负例均拒绝。6项统计测试及Ruff通过。
- 本校验器当前固定单轮iteration=0；nightly多轮、完整来源/Intent/Completion语义重放、性能和恢复等仍待实现。没有重新运行未改动的daemon代码。

### D/G Runtime Security PR与nightly门禁接入

- 新增runtime-security.yml：PR/main运行合同/配对/指标单测、20对真实场景与独立公共证据验证；nightly及手动触发额外三轮隔离全量运行，各自上传公共report/sha256，不复制私钥/token状态目录。
- 依赖沿用Control API uv.lock，所有Action固定SHA、contents:read；upload-artifact固定SHA经官方git远端v4.6.2引用核对。check_contracts.py验证20对、全部要求类别、文件ID一致及正常对照。
- 本地与CI相同的核心命令实际通过：20对40场景、6项统计测试，重新生成报告并Python验证46回执/11效果；Ruff、workflow YAML触发/权限/pin检查通过。报告/tmp/siq-runtime-security-ci-report.json。
- 工作流尚未推送执行，不能宣称远端CI绿色；本地Go为已安装版本，workflow Go1.22需远端确认。nightly强杀恢复/性能埋点仍缺，pending恢复、平台与最终DoD继续进行。

### C2 文件pending签名存储基础

- 新增file-observation-pending/v1合同与Store.SavePendingFile/GetPendingFile：服务端before快照、动作/决策、scope/source、owner摘要、预期摘要/预算/原deadline共同签名；数字使用canon.Decode保留新合同整数表示。
- 0700目录、0600暂存、fsync+排他Link发布，禁止覆盖，独立8192归档上限。同ID同内容并发重试返回同签名；不同预期摘要冲突。原始路径、内容、token不落盘。
- 真实文件采样→签名存储→重建Store读回测试通过，覆盖8路并发、owner篡改、路径穿越、隐私断言。Go全模块race/vet与四平台编译通过（/tmp/siq-pending-store-race.log）；schema正例及raw token/path负例通过。
- 尚未接入begin/finish HTTP，不宣称pending跨重启已可续用。后续需管理接管、撤销终态、deadline/动作复核、强杀恢复及容量/中断故障矩阵；完整目标仍进行中。

### C2 begin API写前持久化与快照重用

- 文件begin成功201前调用SavePendingFile，持久化失败不能创建内存成功状态；已有签名pending先校验owner/source/scope/action/resource/digest/budget/deadline，同内容有效重试重建索引返回原before。
- HTTP真实文件测试在写入后删除内存索引，原token重试仍返回写前不存在快照；同source/scope新token409拒绝接管，随后finish继续得到正确真实材料与Completion。
- Go全模块race/vet及四平台编译通过（/tmp/siq-pending-begin-race.log），diff检查通过。接口保持body/response合同兼容，状态变化先回写规格。
- 当前只支持有效原token的索引恢复；重启token失效后仍需管理恢复、持久撤销与强杀测试，不能宣称跨重启恢复已完成。

### C2 Observer持久撤销终态

- 新增effect-observer-revocation/v1签名存储：owner摘要/时间，0600/fsync/排他Link不可变发布，8192条独立上限；同owner并发重试返回原签名，不改原撤销时间。
- DELETE observer先持久化再删除内存，状态失败不返回204；每次observer校验复核撤销存储。测试把已撤销session重新放入内存，原始HTTP仍拒绝，避免仅依赖内存删除。
- 重建Store后终态保留、8路并发、撤销时间篡改拒绝测试通过；Go全模块race/vet和四平台编译通过（/tmp/siq-observer-revocation-race.log），schema正负样例通过。
- 后续显式pending管理接管必须复核原owner终态；该API/强杀恢复仍未实现，完整目标继续。

### C2 接管历史签名与持久存储

- 新增FileRecovery链模型，绑定完整已签名pending与前一记录摘要，验证连续序号、全部签名、采样/接管时序、原deadline和64次上限。重新签名但改变序号、pending或链关系仍被拒绝。
- 新增RecoverPendingFile/PendingFileOwner存储方法：expected_owner比较后追加、0600/fsync/排他Link发布、当前owner幂等；每次读取有效owner或追加均检查原始及全部历史owner的撤销终态。
- 实际测试通过：8路并发同请求只返回同一签名、重建Store读回、旧owner并发请求冲突、原deadline到期、历史owner撤销后禁止新接管、存储签名篡改及64/65边界。Go全模块race/vet、四平台编译通过（/tmp/siq-recovery-history-race.log）；schema正例与四类结构负例通过，未将结构样例当验签证据。
- 管理恢复HTTP及begin/finish接入尚未完成，强杀真实进程恢复仍待验证；这些存储方法本身不替代source/scope、动作有效性或管理权限复核。同UID整段历史删除/回滚仍不超出可信状态目录边界。

### 最新整体估算（2026-09-08，接管存储增量后）

整体工程进度约75%–80%，不是45项DoD通过率。前文65%–70%为历史检查点。当前已具备20对组件场景、公共回执离线验签及本地验证的PR/nightly工作流；主要剩余为恢复API与强杀测试、平台自动采集/调度、阶段性能与完整语义重放、远端及全仓验收、文档与最终报告。工作流尚未推送运行，不宣称远端CI通过。

- Schema验证补充：本机jsonschema环境未启用RFC3339格式检查依赖，首次日期字符串负例没有拒绝；不计为通过。随后明确验证sequence越界、owner格式、额外token字段和signature格式四类结构负例，均通过；运行时日期由Go time.Parse及上述时序测试约束。

### C2 管理接管API与begin/finish持久owner复核

- POST /v1/file-observation-recoveries仅admin，接收observation_id/observer_id/expected_owner；匹配已签发observer的source/scope、期限/撤销和fileAction，持久CAS接管后清理缓存，返回签名接管记录及原deadline。已完成证据拒绝接管。
- begin重建索引使用持久当前owner及原before；缓存命中和finish也检查全部历史owner撤销。新owner接管后旧token无法begin/finish。finish先读取已有签名材料，覆盖证据已发布但缓存Completed未更新的崩溃窗口，避免重新采样改变证据。
- block/warn真实文件HTTP测试通过：decision凭据403、observer凭据在admin认证域401、admin接管幂等、期限不变、新owner沿用写前快照、旧owner拒绝、原owner撤销后当前owner也拒绝、完成后接管409、缓存未更新重复finish返回相同签名。首次测试误期望observer在admin域403，核对现有认证实现后改为401；权限没有放宽。
- Go全模块race/vet与四平台编译通过（/tmp/siq-recovery-api-race.log）；新请求schema正例与四类负例通过，diff检查通过。尚未验证真实进程SIGKILL/重启恢复，平台调度、故障容量矩阵及完整目标验收继续待完成。

### C2/D/G 真实SIGKILL双重启恢复检查

- 新增recovery_fixture.py，使用生产daemon、隔离状态目录和实际Grant/Intent allow。两个pending先采样再实际写文件，SIGKILL并确认退出码后重启，旧token拒绝、新token需admin显式接管；原before保持不存在，真实after摘要正确且Completion verified。
- 接管observer撤销后第二次SIGKILL/重启，第三个observer恢复剩余pending409；第一次已归档效果跨重启完全一致。结束执行binary verify，报告仅导出公共回执/接管/效果/Completion，临时凭据状态清理。
- 实际命令python3 benchmarks/runtime-security/recovery_fixture.py --out /tmp/siq-recovery-process-report.json通过（4bba77f daemon）；两次确认SIGKILL，未将单纯丢缓存当进程恢复。benchmark目录Ruff、6项统计单测及diff检查通过。
- PR/nightly追加此检查并上传独立recovery报告/摘要；工作流尚未推送执行。该报告不计入20对场景分母，现有evidence.py不支持其完整独立重放。断电、各中断点、期限/容量/并发完整矩阵和native平台调度仍待完成，目标继续进行。

### C2 接管并发、容量与异常状态矩阵

- 新增8个不同owner同时对同一expected_owner发起接管的race测试，严格只有一个成功、其余冲突，持久历史仅一条。
- 通过实际Store连续发布64次接管，第65次ErrCapacity且当前owner不变；在容量上限重试当前owner仍返回第64条原记录。
- 恢复历史缺首序号、未知字段、符号链接、超4096字节均失败关闭；崩溃遗留未发布临时JSON不替代当前有效记录。
- block/warn管理HTTP覆盖source_id/platform/session/agent/task不匹配及目标凭据到期/撤销，全部拒绝，并逐次复核原owner未改变。到期子例明确直接调整测试内存session期限，真实进程时间测试另计；不将此例冒充真实等待到期。
- Go全模块race/vet与四平台编译通过（/tmp/siq-recovery-matrix-race.log），diff检查通过。断电/文件系统故障注入、完整固定签名跨语言语料、平台自动调度及性能/最终验收仍待后续完成。

### C2 Go/Python固定接管签名语料

- 固定Go生成的pending及连续两次recovery样例；Go测试重新构造并签发相同对象，逐字比较固定文件，测试不自动改写语料。
- Python独立Ed25519验证三份签名、对应schema、完整signed pending摘要、前记录摘要、序号、owner变化与时序；篡改owner和把整数预算1024改为1024.0均验签失败。使用公开测试seed，不含真实凭据。
- Python test_schema_contracts.py全部68项通过，Ruff通过；Go effectevidence包race/vet通过。仅增加测试和样例，没有修改生产行为，不重复上一轮已通过的四平台编译。
- Runtime Security PR步骤增加该Python合同测试；远端CI尚未执行。固定样例证明跨语言合同一致，不替代真实恢复报告的完整独立重放和外部信任锚；完整目标仍进行中。

### D 决策阶段单调时钟采样基础

- Engine.Options新增仅宿主可注入的StageTiming回调，默认关闭，客户端不可配置；测量intent_lookup、绑定/合同authority_validation、runtime_action_normalization、context_validation、provenance_resolution、policy_evaluation和receipt_append_fsync的实际执行边界，不改签名回执合同。
- 使用time.Now/Since单调时钟，与授权Now分离。未进入的context或被Authority拒绝后跳过的provenance/policy不产生0样本。provenance样本包含实际checkProvenance入口开销，V2/optional无来源时可能仅执行其兼容判断，不能冒充完整来源图解析。
- 新测试冻结授权时钟仍获得实际耗时，对比开启/关闭计时的action/reason相同，并检查required缺绑定与optional路径的样本分母。Go全模块race/vet及四平台编译通过（/tmp/siq-stage-timing-race.log），diff检查通过。
- 尚未接入效果处理计时或基准报告导出/P50/P95/P99，当前只是实际阶段埋点基础，不宣称性能目标完成。回调在引擎锁内调用，宿主须非阻塞且不可重入；不暴露到普通决策客户端。

### D 八阶段实际性能基线与报告

- 新增两个显式启用的Go性能fixture：真实签名V3/USER来源/上下文/Grant决策七阶段；真实文件材料的SubmitFile效果处理阶段。各预热5次、采集100次，逐次验证成功结果。效果Action为独立受控构造，明确非决策端到端执行；效果计时包含验签相关处理/签名/发布，不含采样及工具执行。
- performance.py实际执行未插桩Go测试，导出800个原始样本、八阶段nearest-rank P50/P95/P99、环境、commit及源码摘要。修复Go JSON输出按事件分段导致长日志解析失败，重组后完整报告生成通过：/tmp/siq-stage-performance.json。
- 性能fixture另以race执行通过，相关包vet和benchmark目录Ruff通过；race耗时不进入性能报告。仅新增测试/runner，未修改生产代码，不重复四平台编译。PR/nightly增加独立performance.json产物，尚未远端执行。
- 该基线满足真实八阶段组件采样起点，但尚未覆盖攻击/拒绝/深图/并发/冷启动性能矩阵；不能将100个暖态样本外推SLA或拼成端到端延迟。完整目标的其他平台、证据语义重放及最终验收继续进行。

### G T27–T35、能力边界与CODEOWNERS

- threat-model.md新增九项Threat→Control→Negative Test→Residual Risk映射及组合不变量，覆盖context伪造、来源伪造/重放/洗白、高影响参数、假成功、deny后效果、效果伪造和覆盖缺口；逐条链接当前测试，保留同UID、观察独立性、隐式lineage和非原子撤销等边界。
- 能力矩阵新增当前V1组件覆盖表，不提升native平台综合支持等级；明确20对场景、八阶段微基准、两次SIGKILL与未完成平台/离线重放/远端CI的区别。
- 新增.github/CODEOWNERS，以仓库owner @maoyadongsh覆盖模板要求的全部核心路径，并覆盖effectevidence/completion/context/适配器/基准和规则文件本身。未修改GitHub Ruleset，main protection仍需独立核验。
- capability honesty门禁、新增文档相对链接/测试符号核对、必需CODEOWNERS路径存在性及diff检查通过。仅文档/审阅路由改动，不重复运行生产代码测试。README整合、最终逐项DoD报告及完整目标其余任务继续待完成。

### B 全局Intent撤销存储与绑定解析

- 核查发现既有revoked_intent类别实际只有绑定撤销；新增intent-revocation/v1终态合同与RevokeIntent/GetIntentRevocation，不以循环撤销当前binding替代全局终态。
- 原Intent与各binding不改写，4096上限、expected digest冲突、签名排他发布及同内容并发幂等。ResolveBinding在authority读锁内每次复核全局撤销，保留已验证合同/绑定供deny回执；Bind拒绝撤销后的新会话。Get/List仍供历史审计，不表示授权有效。
- 实际两个会话撤销前均有效、一次全局撤销后重建Store两者都intent_revoked；8路重试同签名，新绑定拒绝、原合同字节保持、篡改全局摘要失败关闭。Go全模块race/vet及四平台编译通过（/tmp/siq-global-intent-revocation-race.log），schema正例/四类结构负例与diff检查通过。
- 管理HTTP、三模式/hold复核与多会话实际benchmark下一步接入；不宣称全局撤销场景已在20对基准中完成。固定跨语言语料、全局撤销容量/并发解析矩阵继续待补。

### B 全局Intent撤销管理API与执行前复核

- POST /v1/intents/{id}/revoke及GET /revocation复用capAdmin，严格expected_intent_digest请求；decision凭据403、错误摘要409、未知字段400、同内容重试及读取返回相同签名。旧GET合同保持原签名，撤销后新binding拒绝。
- 新增required/optional × block/warn/audit_only六组合决策回归：撤销前allow，撤销后及重建Engine后均hard deny、无advisory/policy放宽且保留任务元数据。真实read_file hold批准后全局撤销，hold-status变denied；没有只测共享谓词来替代实际hold状态流。
- Go全模块race/vet与四平台编译通过（/tmp/siq-global-revocation-api-race.log），请求schema正负例及diff检查通过。全局撤销实际daemon多会话benchmark仍待下一步加入；全目标仍进行中。

### D 全局Intent撤销真实双会话场景，累计21对

- 新增revoked-intent攻击/正常对照，不替换绑定撤销场景。实际daemon部署一个V3 Intent的两条会话绑定与各自有效USER来源，撤销前均allow；一次全局POST revoke后两者均intent_revoked，无关Intent正常对照allow。
- 报告导出全局签名撤销记录、两条前置探针及第二会话拒绝ID；额外探针不重复进入场景分母。21对42个观测全部实际运行通过，报告/tmp/siq-runtime-global-revocation.json，独立evidence.py验51条回执/11个效果封套通过。
- 另用Python Ed25519实际验证全局撤销签名与双会话前后回执关联通过；此检查尚未集成通用离线验证器，未声称完整Intent撤销语义离线重放已完成。21对schema、6项统计测试、Ruff及diff检查通过；daemon代码本轮未改动。
- D3–D5仍未评估，不把deny推断为执行层阻断；完整平台集成、全部命名指标阶段映射、完整证据语义重放与最终验收继续进行。

### D 全局撤销离线验签与多会话关联自动化

- evidence.py将上一轮手动检查纳入自动门禁：严格撤销字段/schema/reason与带时区时间，使用各关联回执的已验证公钥复验撤销签名；要求同Intent摘要、两个不同会话、五个独立探针/场景引用、撤销前allow/撤销后intent_revoked以及无关Intent正常对照。
- 新增持久单测覆盖有效链、摘要/时间/签名篡改、删除/重复引用、替换会话、前置未授权、后置仍允许、绑定撤销冒充全局撤销及无关对照缺失。全部9项benchmark单测和Ruff通过；现有真实报告51回执/11效果重新离线复验通过，不重复运行未改动daemon。
- README同步自动验证边界；完整Intent/来源图/Completion语义重放、外部信任锚和其他目标任务仍待完成。测试助手接收的actions在通用验证器中先通过回执链验签，助手本身不替代回执验签。


### 集成回归检查（2026-09-08 11:30，095396e）

- Control API：.venv/bin/ruff check app通过；.venv/bin/pytest -q全量534项通过（按完整进度输出核对），没有失败。日志/tmp/siq-control-full-regression.log；既有Starlette/httpx弃用提示不影响结果，本轮没有为警告擅自升级依赖。
- Web：npm run build通过，含TypeScript检查与Vite构建；日志/tmp/siq-web-full-regression.log。
- Edge与全部11个Connector Go模块：每个模块go vet ./...和go test -race ./...通过。模块为edge/agent及connectors/{dify,directory,docker,hermes,kubernetes,mcp,openclaw,piagent,process,systemd,workbuddy}，逐模块日志/tmp/siq-regression-<目录以横线连接>.log。本地daemon模块沿用最近全量race/vet/四平台通过记录，本轮此后无生产Go改动。
- CI已有11项静态脚本通过：事件信封核心、Control API Dockerfile锁、Web响应头、CI Action pin、OpenShell工作流、自托管Mermaid、Pages pin、Docker镜像digest、本地威胁模型、能力诚实性、性能基线骨架。
- python3 scripts/test-openclaw-checkpoint-compat.py的15项测试通过；node scripts/test-openclaw-adapter.cjs通过关联/宿主能力/审批复核门禁。这些是组件/兼容测试，不等同新的原生平台V3来源自动采集验收。
- 全部命令结束且工作树未产生非预期改动。此为本地集成检查，不称作远端CI、生产部署、真实数据库恢复或完整45项DoD验收；尚未推送分支。

### B Hermes宿主引用桥接与旧路径兼容

- Hermes pre_tool_call新增可选parameter_provenance/context_assertion_id宿主关键字，映射到Decide顶层；不从tool args或结果猜测来源，不铸造issuer/trust。内嵌安装资产同步。
- 显式携带Authority引用时，400/503/非法响应均block，包括warn/audit_only，避免来源未验证时退回legacy advisory允许。未携带引用的旧调用保留既有策略表；签名/范围/摘要判断仍在daemon。
- 适配器28项测试通过（含三模式引用透传、参数内伪造不升级、验证失败拒绝），Ruff通过；adapterinstall包race/vet及四平台编译通过。
- 原生Hermes已有V2兼容夹具实际通过：python3 scripts/validate-intent-v2-hermes.py --hermes-root /home/maoyd/siq/hermes-agent --hermes-python /home/maoyd/siq/hermes-agent/.venv/bin/python --out /tmp/siq-hermes-reference-compat.json --load-samples 20 --concurrency 4。使用隔离状态/插件配置，未修改用户实际安装；该次缩小负载验证兼容，不替代完整负载/原生V3来源集成。
- 当前是显式宿主引用桥接；原版Hermes未自动产生这些字段，MCP结果采集与传播仍待接入。不能把fake HTTP映射测试或V2兼容通过称为native V3 provenance已完成。

### B Hermes引用传输异常与字节预算

- 先添加负例并在旧实现实际运行：12例失败，非JSON对象/循环引用异常逃出钩子，NaN/超1MiB引用未在发送前拒绝。测试日志/tmp/siq-hermes-invalid-reference-before.log；大字符串测试参数随后改为短ID，避免失败摘要膨胀。
- _post发送前严格JSON编码、拒绝NaN/循环/不可编码对象和超1MiB请求，返回无有效裁决，显式Authority引用调用由三模式硬拒绝分支处理。响应有界读取1MiB+1，超限不接受allow；内嵌资产同步。
- 42项Hermes适配器测试全部通过，包括恰好1MiB请求允许、+1字节不发送、超响应预算warn也block；Ruff、adapterinstall race/vet与四平台编译通过，diff检查通过。
- 本轮是已复现的传输失败边界修复，不承担来源验签或新增原生自动采集声明；上一轮V2原生兼容证据保留，完整目标继续。

### B Hermes配置化MCP结果自动上报

- 检查原生post_tool_call只提供工具名/参数/结果等信息；MCP原生注册名可能歧义，未依赖名称前缀臆造server。新增mcp_sources精确工具→部署者服务器身份配置，默认空；post hook自动提交实际result，固定MCP/untrusted，服务器身份+工具仅用摘要。
- report_id绑定平台/会话/Agent/工具/call；无稳定call、过大/不可编码结果不登记、不截断伪装完整。成功后仅缓存provenance_id，2048上限/5分钟到期；失败或重复ID报告冲突不能保留旧引用供新结果冒用。宿主可显式取回引用，后续参数派生仍需daemon选择API。
- 44项Hermes适配器测试通过，覆盖精确映射、工具内容自报USER不升级、原内容保持、跨会话取引用失败、容量/失败/超限；Ruff、adapterinstall race/vet与四平台编译通过，内嵌资产同步。
- 本批HTTP测试用fake服务验证映射，不称为原生MCP已接入。下一步实际daemon+MCP调用验证采集/派生/参数引用链；完整目标仍进行中。

### B 真实MCP→Hermes钩子→daemon桥接验证

- validate-mcp-provenance.py新增--hermes-bridge：真实MCP HTTP initialize/tools-call取得结果后，由实际适配器post hook自动上报并缓存引用；调用daemon select生成路径派生引用，检查仍MCP/untrusted。
- 实际pre hook提交该引用，daemon V3拒绝、适配器block；admin USER同值来源经相同pre hook允许。单独HTTP决定保留明确reason断言，结束回执链verify通过。报告/tmp/siq-hermes-mcp-daemon-bridge.json，本轮运行passed=true。
- 此模式直接调用适配器hook，不声称原生Hermes MCP注册/调度器已接入；不修改实际用户配置，不执行目标read工具或冒充独立效果。已有21对基准默认行为保持，PR/nightly新增独立桥接报告步骤。
- Ruff、实际桥接报告断言与diff检查通过；生产代码本轮未改，不重复Go全量测试。原生生命周期和跨平台引用集成等完整目标任务继续进行。

### G README实验性能力与授权语义同步

- README顶部改为当前开发分支状态，不把本地成果归于远端main/Release；移除“Provenance DAG未实现”和“required必须block才拒绝”的陈旧表述。
- 增补最小用户说明：V3签名来源/最低父trust、三模式Authority硬拒绝与legacy边界、绑定/全局Intent撤销、实验性效果材料/Completion、恢复接管及四个可复现基准命令。保留同UID、partial观察、性能非SLA和平台未完整集成的限制。
- 原生MCP执行边界复核：Hermes实际dispatcher未知mcp工具名不会自动变成可信已知effect；当前统一描述保留unknown，不能为夹具放宽bound Intent。配置化采集与直接hook桥接不代表原生注册/执行授权链完成，README已明确。
- README相对文件链接、capability honesty及diff检查通过；仅文档改动，不重复生产测试。完整目标与最终逐项验收仍待继续。


### 远端分支及CI核验（2026-09-08，54f5d32）

- 独立开发分支已推送，草稿PR https://github.com/maoyadongsh/siq-agent-security/pull/4 保持OPEN/draft，尚未合并main；工作树起始与upstream一致。
- gh pr view 4实际返回当前head 54f5d327ecc726058d0c7d25fff4440716227340，30项检查SUCCESS、runtime-security-nightly按触发条件SKIPPED，无失败；包括runtime-security-contracts、Control API、Web、本地daemon、Go1.22/stable Edge与全部Connector、gitleaks。不是nightly运行成功或最终45项验收完成的证明。
- 整体工程进度当前保守估算75%–85%（中心约80%），不作为45项DoD通过率。此前65%–70%为旧基线历史估算。平台集成、完整证据语义重放、验证矩阵与最终逐项报告仍待完成。

### B Hermes Authority引用关联失败拒绝

- 新增三模式×context/provenance引用×缓存冲突/容量耗尽12项负例；修复前8项失败，warn/audit_only在关联失败后错误返回允许。日志/tmp/siq-hermes-correlation-before.log。
- 显式Authority引用的allow响应无法建立关联时，钩子现在返回block；不改变daemon裁决，保留未带引用legacy调用的原策略。内嵌安装资产同步，规格先行更新。
- adapterinstall race/vet及四平台编译通过；真实MCP→Hermes hook→daemon桥接重新通过，4条回执链验证成功，报告/tmp/siq-hermes-correlation-bridge.json。报告基于54f5d32加本次工作树修改，不标为该提交干净构建；仍只证明组件桥接。
- Hermes完整适配器56项测试与Ruff通过；diff检查通过。本次修改尚无对应远端CI结果，不能沿用54f5d32绿灯作为新提交证明。


### B 全局Intent撤销跨语言固定向量

- 新增intent-revocation.sample.json，使用公开测试seed 7及固定纳秒时间，由Python生成签名；Go使用生产intentRevocationMap/SignCanonical重建全部字段并断言签名相同，同时以生产GetIntentRevocation读取固定记录。
- Go分别篡改摘要、纳秒时间、ID、reason/schema/signing_schema和签名，均拒绝；Python独立验证schema（启用date-time检查）及Ed25519签名，逐个签名字段篡改和零签名均拒绝。没有修改生产行为或新增自定义签名算法。
- Python完整合同69项、Ruff通过；Intent包race/vet及diff检查通过。此证据证明合同签名对等，不替代容量/并发解析完整矩阵或全目标验收。


### B 全局撤销容量与并发解析边界

- 新增容量边界：预置4095条有效签名记录（直接准备夹具，避免每次发布重复扫描），第4096条实际RevokeIntent发布成功；满容量同请求重试返回原记录，第4097条拒绝且没有落盘，目录数量保持4096。
- 新增16读取者、两个会话的并发ResolveBinding与一次全局撤销；重叠阶段仅允许有效或intent_revoked结果，撤销调用返回后以channel同步的160次解析全部intent_revoked并保留合同/绑定摘要。
- Intent全包race/vet与diff检查通过。未修改生产实现；该测试不声称撤销可取消已经开始的外部副作用或提供跨进程原子执行。
- 远端92b9efe检查已实际触发，检查时仍为排队/运行中，nightly按触发条件跳过；本批新增测试尚未取得对应远端结果。


### 最终验收索引起步

- 从用户模板逐项提取45项DoD，建立[验收索引](provenance-bound-effect-v1-acceptance-audit.md)，保留原文要求、当前源码/测试入口与待核读状态；脚本核对45项齐全且全部本地链接目标存在。
- 明确fixture证明边界、三平台现有核心测试需求，以及新增map/signing/LLM授权须全diff审计；不把找到测试文件直接计作验收通过。
- 核读metrics.py发现统计口径须在报告显式说明：benign completion只统计有Completion的样本，unknown effect只统计有effect_record的样本；后续报告需展示未覆盖数量，不能按42观测整体完成率宣传。
- 本轮是验收资料落盘，无生产代码修改；diff检查通过，完整目标保持进行中。


### D 命名指标覆盖分母显式化

- 每项命名指标新增sample_count、excluded_count与population，保留原分子/分母/rate；全体与按kind统计各自使用真实总数。excluded包含不适用及缺记录，明确不同于D0–D5的not_evaluated，也不能当失败。
- 新测试覆盖混合attack/benign、缺效果记录、仅一个verified completion及空总体，11项benchmark单测、Ruff/diff通过。
- 实际21对基准重新执行通过：/tmp/siq-runtime-population.json；evidence.py独立复验51条回执和11个效果封套通过。旧报告需使用对应旧版验证器，新统计不静默回写历史产物。
- 核实远端92b9efe：当前可见29项SUCCESS、1项nightly SKIPPED；此结果不覆盖其后的本地提交/修改。


### 三平台核心兼容集中核验与CI补漏

- 完成Hermes默认200样本/8并发原生夹具（412回执）、CodeBuddy原生CLI（13回执）及10项bootstrap故障/恢复、OpenClaw钩子与15项checkpoint兼容验证，结果全部通过；详见验收索引的命令表及公开摘要。
- Hermes适配器56项及Ruff、Go cmd/adapterinstall/server race通过；新增Hermes Python回归CI步骤，弥补此前远端仅桥接夹具未跑完整适配器负例的缺口。
- 所有原生测试用隔离临时配置/合成输入，不修改用户配置，不声称V3原生集成或生产支持。仅CI/文档修改，diff检查通过；本批对应远端结果待推送后确认。


### 状态容量与签名复用源码审计

- 新增[状态审计](provenance-bound-effect-v1-state-audit.md)及生产新增集合/签名调用索引；核读observer、pending、来源图/matcher、Completion、历史效果查询与oracle边界，记录具体上限和失败行为。
- 发现RuntimeAction高影响路径临时集合目前依赖4MiB HTTP输入边界，没有独立节点/深度/输出预算；后续需评估并避免截断导致授权漏检。未把“无持久无限增长”误当完整资源防护完成。
- 签名核读确认主要新增记录继续走既有signing/canon；完整diff和离线工具预算继续待审，不以搜索命中代替G3/G4/G5最终验收。本轮仅审计文档，diff检查通过。


### RuntimeAction遍历预算及三模式拒绝

- 补上审计发现的参数遍历边界：根深度0、最大64层/8192值节点、单指针1024字节/累计1MiB；描述器递归前预检，循环引用也在深度预算内终止。超限不返回部分资源或来源路径。
- 修复前深度/节点/指针超限三例实际失败（/tmp/siq-budget-before.log）；修复后边界、累计预算、循环引用及三模式Engine hard deny通过。签名拒绝保留原JSON参数摘要，跳过文本扫描和policy；非JSON可编码Go输入显式报错，不再忽略Marshal错误生成空摘要。
- Intent matcher同样将预算错误作为runtime_parameter_budget_exceeded拒绝。规范先更新；不是截断参数后继续放行，不扩展任何权限。
- Go全模块race/vet及linux amd64/arm64、darwin arm64、windows amd64编译通过（/tmp/siq-budget-full.log）；Python合同69项及实际MCP→Hermes→daemon桥接通过、回执链验证成功（/tmp/siq-budget-mcp.json）。diff检查通过。
- 当前只限制遍历与指针构建；总HTTP字节边界和JSON编码仍沿用既有上限，不宣称CPU/内存固定SLA。全目标其余集成/证据任务继续。


### D 恢复链签名材料归档与独立验证

- 强杀恢复夹具导出原始签名pending，新增recovery_evidence.py在无daemon情况下验证schema/签名、原pending摘要、序列/前置hash、owner更换、原始expiry，纳秒时间不截为微秒。
- 复用固定向量的正例、缺序/乱序/超长历史、owner/expiry篡改及纳秒精度测试通过；benchmark单测共14项、Ruff通过。
- 真实两次SIGKILL恢复重新运行成功：/tmp/siq-recovery-archive.json；离线验证2份pending/2条接管记录通过。PR/nightly均新增该验证步骤，diff检查通过。
- 该验证仍不证明外部信任锚、SIGKILL事件真实性或完整Completion/历史撤销语义；这些剩余范围不被收缩或冒充已完成。


### D 恢复owner撤销材料验证

- 恢复夹具归档真实effect-observer-revocation签名记录，仅含owner摘要及时间；离线验证schema/签名，并关联两条接管记录owner、严格比较纳秒时序。
- 新负例包含有效签名但错误owner、有效签名但早于接管1ns，以及无效签名；15项benchmark单测和Ruff通过。
- 真实两次SIGKILL夹具重新运行通过（/tmp/siq-recovery-revocation.json），独立验证2份pending/2条接管/1份撤销通过；diff检查通过。
- 验证不等于独立证明HTTP409或SIGKILL事件，也不替代完整Completion语义。生产代码未改，不重复Go全量门禁。


### D 恢复pending与原始签名授权动作关联

- 提取共享verify_receipt_bundles，主基准和恢复验证器复用链序列/hash/Ed25519验证，增加64 bundles/65536 receipts输入预算；不另写第二套回执算法。
- 恢复pending须对应同task/session/agent/platform、action/receipt、filesystem资源和file.write allow决定；Authority valid且采样时间不早于决定。错配及有效链内容篡改/重复回执负例通过。
- 16项benchmark单测、Ruff/diff通过；已有真实恢复报告离线验证1条决定回执、2pending/2接管/1撤销通过，原21对报告51回执/11效果封套重新验证通过。
- 无需重复未变更的daemon，未把提供的完整前缀当作外部checkpoint证明；完整Completion语义与原始Intent材料仍需后续补齐。


### D 恢复文件完成链离线复核

- 归档签名Intent V3，验证原合同摘要/签名与决定的Intent/task/Agent关联；效果记录双层签名及file material摘要复验，要求资源、预期内容、原before和observer一致。
- 单文件夹具从已验证材料重算verified Completion并精确比较输出；效果时间须处在接管之后、撤销之前且原pending未到期。公开真实报告已落盘至docs/evidence/provenance-v1/recovery-completion-20260908.json。
- 真实两次SIGKILL恢复及离线验证通过：2pending、2接管、1撤销、1授权回执、1文件Completion；新增真实归档的完成状态/引用/内容/Intent/动作/缺回执负例，17项单测和Ruff/diff通过。
- 这完成了该恢复夹具的文件完成链验证，不缩减为全任务通用重放；网络、多要求、conflicting/unknown组合及全目标其他工作继续待完成。


### 集中集成门禁（95e425c）

- 最新21对安全基准、单文件恢复链离线验证、八阶段性能、17单测/Ruff全部通过，详见[集成报告](provenance-bound-effect-v1-integration-20260908.md)及真实统计归档。
- 明确D5只评估11/42样本，其余31未评估；positive表示该层目标效果，不一概是攻击成功。远端30c7656必跑检查成功，后续提交必须重新验证。
- 本轮以实际输出更新证据与分母，不重复未改变模块门禁，不宣称完整目标完成。


### 模板范围复核与严格漏洞门禁

- 复核§33–36：本轮MCP MVP要求真实外部来源、显式/确定性lineage，不要求一次覆盖全部来源或模型语义传播；§79要求薄适配器和explicit handles。后续验收必须依原文范围，不能以任意平台全自动集成替代该范围，也不能漏掉明确要求。
- §102要求govulncheck。实际Go1.26.5扫描发现5项可达标准库漏洞，原CI仅warning不能作为无漏洞证明；Go1.26.6复扫未发现漏洞。
- 新增独立严格runtime-security-toolchain CI任务，固定修复版本并执行govulncheck/race/vet；保留旧Go兼容路径。本地Go1.26.6全模块race/vet通过，README及[工具链报告](provenance-bound-effect-v1-toolchain-20260908.md)更新，diff检查通过。
- 未替换全局默认Go或历史产物，安全发布需修复工具链重建；未把此模块扫描外推为所有Connector无漏洞。完整目标保持进行中。


### §89 来源签发—Decide—撤销并发

- 新增真实provenance.Store与Engine集成并发测试：每模式16个线程签发独立USER来源并Decide，全部首次允许后并发Decide与issuer撤销；撤销返回后每线程4次决定全部hard deny、无advisory、provenance_issuer_untrusted。
- 覆盖block/warn/audit_only三模式，实际产生48次发布后允许及192次同步撤销后拒绝，另有并发重叠阶段允许/拒绝检查。使用等待屏障明确撤销完成边界，不将重叠请求顺序猜测为原子外部执行。
- 初次race发现既有测试夹具Now推进fx.clock与签发线程读时钟竞争；改为线程启动前固定签发时间快照，未改生产锁语义。随后Go1.26.6 receipt全包无缓存race及vet通过（/tmp/siq-provenance-decision-concurrency.log）。
- 本轮仅增加集成回归，未改生产代码；不重复四平台编译。完整目标继续进行中。


### §90 合同真实日期校验修复

- 实测原环境FormatChecker未注册date-time，2026-02-30T00:00:00Z被接受；仅声明format不足以证明日期已校验。新增开发依赖rfc3339-validator（锁定0.1.4及six1.17.0），不改变生产Go依赖。
- provenance合同助手启用FormatChecker；6份已签名固定样例（Context/Effect/pending/recovery/global revocation/Intent V3）验证真实日历、时区缺失、非法小时/月、额外属性和每个必需字段缺失；issuer增加真实日历负例，并显式断言checker已注册防止环境静默跳过。
- 合同相关95项通过，Control API全量542项通过及Ruff通过（/tmp/siq-calendar-contract-full.log）；17项benchmark单测通过。修正draft-07 HTTPS元模式的验证器选择后6项calendar重新通过，无该回退警告。既有Starlette弃用提示未擅自升级处理。
- 该修复提高合同验收可信度，不声称此前生产Go日期解析失效，也不把这7份合同覆盖当作全部新schema的最终§90验收。diff检查通过。


### Authority五项本地验收收敛

- 核读生产Authority分类/模式应用、Context受信读取和请求绑定、对应测试断言，将A1–A5在验收索引中标为本地验收通过，注明模拟错误矩阵与真实签名集成的证明边界。
- 补齐真实签名会话required/optional×三模式×运行/重启后的降级拒绝12组合，保留bound摘要，无advisory。此前简单downgrade测试仅block，此批不再用它代表全模式恢复。
- Go1.26.6 receipt/intent/server相关无缓存race、receipt vet与diff通过（/tmp/siq-authority-acceptance.log）。其他40项及全模板验收不因这5项通过而自动完成。


### Provenance十项本地验收收敛

- 核读签发者权限/验签、参数内容与scope绑定、图解析/聚合/unknown、受限上报及高影响默认约束，验收索引P1–P10标记本地通过，并逐项记录测试及证明边界。
- Go1.26.6 provenance/receipt/server相关无缓存race通过（/tmp/siq-provenance-acceptance.log）；Python provenance合同7项通过；真实MCP桥接4回执离线链验证通过。
- 与A组累计15项本地核心DoD有逐项核读与运行证据；这不是整体工程百分比或全模板通过声明。固定向量完整性、剩余DoD及最终交付仍继续。

## 2026-09-08：集中验收与Provenance跨语言向量补齐

- R1–R4、E1–E8完成源码/测试核读与本地验收；五包Go1.26.6无缓存race通过，Effect Python合同13项通过。累计27/45项明确本地验收，不等于整体开发完成率。
- 模板§91新增ProvenanceAssertion共享固定样例与向量，Python生成、Go生产canon/signing与VerifyAuthority复核：中文、非BMP字符、HTML字符、换行、整数的canonical bytes、内容摘要、unsigned摘要、确定性签名一致；逐个signed字段篡改拒绝。
- 首次Go测试暴露测试夹具把整数解码成float64（7变7.0）；改为RawMessage与生产canon.Decode保留数字类型后复核。没有修改生产canonical规则或放宽断言。
- 既有集成报告再次独立验证51条回执及11份效果封装，不宣称重新运行观测。远端e70541e的ci/runtime-security两工作流均success；新增本地提交仍需对应远端CI。
- 后续集中推进B/C/G、§90全部新schema负向矩阵及§115最终Engineering Report；保持按模块整批完成，针对变更运行必要门禁，避免无变化重复全仓回归。
- 本批最终验证：Provenance完整包Go1.26.6无缓存race与vet通过；Python来源合同8项与Ruff通过；git diff --check通过。

## 2026-09-08：§90来源合同矩阵及CI覆盖

- 新增test_provenance_schema_matrix.py，覆盖7份来源schema：Assertion、TrustedSourceIssuer、issuer record/revocation、report/select request、parameter binding。53项参数化测试包含每层受约束对象必填字段删除、额外权限字段注入、坏ID/签名格式/摘要/日历时间/source/trust/scope/parent及容量正负边界。
- content是合同允许的任意JSON，未错误地对用户内容要求封闭字段；schema不验证密码学签名、时序或父图可信性，继续由Go authority/graph测试及共享签名向量证明。未包含的schema类别记为不适用，不伪造签名字段。
- runtime-security workflow显式执行来源合同、来源矩阵及Effect合同，避免只执行旧test_schema_contracts.py。主CI原有全量pytest继续保留。
- 本地执行CI对应四个文件共149项通过，Ruff及diff检查通过；尚未宣称26份新增schema全部§90验收完成。后续继续其余Context/Effect/Recovery/Intent合同适用负例覆盖与B/C/G验收。

## 2026-09-08：B组验收与D5离线验证缺口修复

- 核读B1–B6源码与21对42场景，更新验收索引为累计33/45项本地验收；非项目完成百分比。
- 修复evidence.verify无effect_record时直接continue导致伪造D5进入指标的问题；新增verify_effect_reference要求归档效果、当前decision关联、正确evidence ID及实际观测材料。
- 使用既有完整集成报告，在无效果样本注入独立oracle自声明并重算summary：HEAD旧版verify接受，修复后报D5 requires an archived effect record；没有修改原始报告文件。
- 新负向测试覆盖假success/假failure、跨decision借用、错误/多余refs、缺材料。19项基准测试、Ruff通过；原始报告51回执/11效果封装仍通过；check_contracts确认21对42场景20类别。
- 后续继续C/G及剩余schema与最终工程报告；本轮不宣称所有离线策略/任务完成语义已经通用重演。

## 2026-09-08：C组兼容验收

- 基线6f1941b完成C1–C6核读及本地验收，累计39/45项；不是整体完成率。
- Go1.26.6 intent/receipt相关双读/历史验签/撤销/legacy测试无缓存race通过；adapterinstall、cmd/agentshield完整包无缓存race通过。
- OpenClaw hook审批复查通过，checkpoint兼容15项通过；Hermes adapter56项通过。原生Hermes/CodeBuddy旧夹具保持原基线与限制，不冒充本轮重跑。
- 准备推送本批测试与验证器修复到独立开发分支，远端CI以实际最终SHA另行验收；main保持不变。

## 2026-09-08：落实§104不同规模基准套件

- 发现PR/nightly原先同为21对，只重复次数不同，不能称nightly更大语料。新增明确--suite smoke/full：PR实际执行5对10场景，nightly保留完整21对42场景及网络oracle/恢复/三次重复。
- 验证器由调用者指定expected_suite，缺省full；拒绝report自行降级。严格要求对应场景集合完整，保留旧full报告兼容。
- Go1.26.6实际smoke运行通过，独立验证10条回执、8份效果封装；将该报告改名full和删除一个smoke场景后重算summary均拒绝。现有full报告51回执/11效果封装仍通过。
- 21项基准unittest与Ruff通过；没有改生产授权语义。1e162dc远端ci排队、runtime-security运行中为本轮查询时状态，新套件变更仍需下一提交CI验证。

## 2026-09-08：Engineering Report A–K草稿与剩余口径缺口

- 新建provenance-bound-effect-v1-engineering-report.md，汇总实际基线、架构、六类信任主体、关键文件、INV-1–7、负向结果、分母明确的基准、真实性能、兼容性、CI及残余风险。最终SHA仍未确定，文件明确为验收草稿，不当作全目标完成证明。
- 表格从已归档95e425c integration-summary读取实际值，未杜撰当前性能或将阶段百分位相加。发现完整decision耗时与policy_evaluation不是同一口径；最终报告必须补齐或明确端到端性能证据。
- 远端1e162dc的ci与runtime-security工作流均success；442007b及本次文档待新CI，不沿用旧结果冒称全绿。
- 当前继续G组、剩余schema与逐节覆盖审计，保持目标进行中。

## 2026-09-08：完整Decision性能证据

- 补充TestRuntimeStageBaseline的decision_total计时，包围整个Engine.Decide，保留原七个内部决策阶段；逐样本验证内部阶段不超过总调用耗时。性能脚本要求独立总计时存在，未改变benchmark结果中的阶段指标口径。
- performance.py将显式GOTOOLCHAIN传入受限环境，报告确认Go1.26.6 linux/arm64。实际5次预热+100次采样，完整Decide P50/P95/P99=7.818665/12.52045/12.676101ms。
- 归档完整原始数据与源码哈希，Engineering Report区分该工作区采样和95e425c历史阶段数据。不是HTTP端到端或生产SLA，不把阶段百分位相加。
- 实际性能测试与逐样本包含关系检查通过；receipt vet、Python Ruff、diff检查通过。仅测试/脚本修改，不改生产路径。

## 2026-09-08：剩余19份合同结构矩阵

- 新增test_effect_schema_matrix.py覆盖Context、Effect/observer/requirement/Completion、文件begin/finish/pending/recovery、网络材料/提交、Intent V3及全局撤销，共19份；结合此前7份来源合同，26份新增合同均已有结构正负矩阵入口。
- 正例复用共享固定向量及已归档真实恢复/Completion记录；对受约束嵌套对象逐项删除必填字段和注入额外权限字段，检查非法ID/签名格式/摘要/时间/taxonomy/字符串与数值容量/数组上限。只解析同目录已提交schema引用，不访问网络。
- 矩阵不等于全部安全语义：例如超长重复数组可能同时违反唯一性，不能替代Go的精确容量上限测试；签名格式通过不等于密码学签名有效，schema也不验证issuer/父图/时序关系。对应Go/HTTP负向及固定向量仍是独立验收依据。
- runtime-security显式纳入新矩阵。五份合同测试共187项通过；Ruff、diff检查通过。生产代码和schema未改动。

## 2026-09-08：G4签名复用验收

- 核对起点至693641d签名/序列化增量及既有状态审计；canon/signing无diff，新增签名合同均复用生产签名路由，未引入第二套生产canonical实现。
- canon/signing完整包与相关模块固定向量/签名/篡改Go1.26.6无缓存race通过；Context测试位于intent，未把trustedcontext无测试文件当成证据。
- 明确Effect旧float投影与pending/recovery整数保留兼容边界；G4本地通过，累计40/45项。G3/G5及全部模板要求继续审计，不因索引匹配就判定完成。
- 693641d远端runtime-security运行中、ci排队（本轮读取），继续保持最终CI未验收。

## 2026-09-08：状态容量与最终授权入口验收

- G3/G5完成生产边界核读，见state-audit增量；区分持久缓存、调用临时map和固定投影，明确磁盘/全链扫描不在固定资源保证内。
- 核对daemon权威依赖注入、内嵌Intent拒绝、Authority ApplyMode、管理路由分权及Completion只读行为；未新增LLM最终授权。
- 六包Capacity/Budget/Bounds/Boundaries/Concurrent/Recovery匹配测试Go1.26.6无缓存race通过，累计42/45项本地验收。
- 693641d远端ci运行34187693641、runtime-security运行34187693678均success；最终交付SHA及全模板审计仍待完成。

## 2026-09-08：45项DoD证据收口（非全目标完成）

- G1/G2基于693641d远端job/step明细验收，归档ci-693641d-20260908.json；所有可执行job成功，nightly skipped不算通过。
- G6完成README/能力矩阵/发布DefaultMatrix边界核对，honesty测试Go1.26.6无缓存race通过。
- 45/45条目现有各自范围的验收记录；CI有明确SHA限定。全模板逐节交付审计与最终报告尚未定版，目标继续进行。

## 2026-09-08：§18–44与nightly完整证据

- 原文§18–44逐节核读并映射实现/合同/既有运行测试；更新全模板审计表。修正provenance API开头过时开发状态，保留MCP/宿主/语义传播限制。
- workflow_dispatch运行34188106080对应693641d，toolchain/contracts与nightly三次full全部success。下载nightly-1产物校验摘要，并本地再次验证51回执/11效果封装及2 pending/2 recovery/1 observer撤销/1恢复回执/1文件Completion。
- 归档nightly SHA/job/产物哈希与重验范围；未把同产物中的摘要侧文件当成独立信任锚。剩余§45–76、79–107与116–120继续核验，报告仍待最终定版。

## 2026-09-08：§45–76逐节核验

- 完成Effect五维合同/独立observer/真实文件与网络/Completion最小语义/完整攻击类别与指标/八阶段性能/威胁模型逐节对应，更新全模板审计表。
- 五类冻结枚举逐一核对相等，T27–T35的19个命名测试均在相邻源码链接中存在。运行证据沿用已归档693641d full nightly和本地独立验证，不虚构重跑。
- 更新威胁模型的旧CI待验证描述；保留原生平台、同UID、业务语义与oracle覆盖残余风险。本轮无生产行为变更。
- 继续§79–107与116–120指定测试/交付项，最终报告仍待定版。

## 2026-09-08：§91三类合同统一固定向量

- 为ContextAssertion/EffectEvidence补充冻结canonical_unsigned/unsigned_sha256文件，与已有Provenance向量一起由Go/Python统一消费。没有改写样例签名或生产canonical逻辑。
- 新增仅测试包internal/contractvectors，使用真实三类Unsigned和既有signing验证字节/摘要/签名一致；Go1.26.6 race与vet通过。Python三向量+原Context合同共5项通过，Ruff通过。
- runtime-security显式加入Context合同与三向量测试；§91在全模板审计表更新为已核验。后续提交仍需新的远端CI，旧693641d不覆盖新增测试。

## 2026-09-08：同动作正负效果材料冲突修复

- 核验指定Effect负例时发现：同一动作同时有有效完成与失败材料，Completion原本返回incomplete，未明确矛盾。新增负向测试先复现旧行为，再按规格返回conflicting/effect_evidence_conflicting并保留两份证据。
- 按(action_id, decision_receipt_id)聚合正负材料，map受已有限制的8192记录约束；不同动作不误合并。无实际材料的失败声明不构成此独立冲突；只有失败仍incomplete，输入顺序不影响冲突。
- 既有HTTP文件恢复测试原期待incomplete，因同动作两份材料现应conflicting，已增强为状态+reason_code断言。未放宽签名/授权检查。
- Go1.26.6完整go test -race ./...最终通过（未变化包有缓存）、go vet ./...通过，linux/amd64、linux/arm64、darwin/arm64、windows/amd64四平台编译通过；51项Effect/结构合同测试通过。
- 此生产修复在693641d CI之后，须重新推送验证，旧CI/nightly不覆盖本次行为。§88具体工具自报与oracle矛盾仍按证据强度区分，不把工具自报提升为可信完成证明。

## 2026-09-08：适配器/治理与Managed边界预留

- 80dfff8已推送独立分支，等待对应新CI；未合并main。
- 新增ADR-018，基于现有Lookup、外部issuer公钥与独立observer能力明确未来跨UID/企业trust bundle接入条件；不新增空接口或生产部署宣称。
- 继续更新§79–107逐节审计：薄适配器、Context/HardGate指定测试、ADR、单进程结构、CODEOWNERS及不修改Ruleset均有对应证据。§82、85、88–90与最终CI仍继续核对，不提前关闭。

### 2026-09-08：撤销 API 回归批次与最新 CI

- 新增 `TestProvenanceReportsRejectRevokedAuthorityAcrossRestart`：block/warn/audit_only × binding/全局 Intent 撤销 × 重建服务前后；先验证 report/select 正常签发，再验证旧 report 重放、新 report 和旧 parent select 均返回 `provenance_authority_invalid`。共 36 次撤销后 HTTP 拒绝断言，覆盖持久状态重新加载。此处重建服务不等同于 SIGKILL 测试。
- 验证：Go 1.26.6 focused race、整个 `internal/server` 无缓存 race、该包 vet 均通过；未改生产实现或合同。
- 生产代码基线 `80dfff8` 的 CI 34188862724、runtime-security 34188862744 均 success；这些结果不包含本次新增测试。
- §82 的 report/select 路径已有明确 HTTP 证据；Effect API 的历史动作观察与撤销后新授权边界仍需逐端点归档，不能据此宣称整节完成。§88 E-05 的“工具成功声明与独立未收到证据”仍需精确核对，已有同动作独立正负材料冲突测试不替代该场景。

### 2026-09-08：E-05 工具声明与独立失败材料冲突

- 先由负向测试复现旧行为：签名 tool_report completed + 同动作独立文件缺失材料返回unknown。修复 Completion，在既有有界 action/receipt 索引中保留成功声明与独立失败的冲突；声明单独存在、无材料失败、跨动作组合不升级为完成或独立冲突。
- 发现现有 observer 管理入口有意不签发 tool_report 凭据，故新增单独 capDecision `/v1/tool-effect-reports`，不放宽 observer 合同。新版本化请求合同先提交为 `0bec5d8`。声明保持 self_reported/unknown，不允许伪造 host 独立性。
- HTTP 测试 TestToolSuccessConflictsWithIndependentMissingOutputHTTP 使用实际文件采样：unknown→conflicting；同时覆盖管理/observer凭据拒绝、伪造独立来源拒绝、错误回执拒绝、相同重放幂等、不同重放409。
- 验证：Go1.26.6全模块vet与race通过（日志 /tmp/siq-tool-report-api-race.log），linux/amd64、linux/arm64、darwin/arm64、windows/amd64编译通过；Python效果合同及schema矩阵53项通过，Ruff通过。最后补充409断言后再运行该HTTP focused race。
- 范围：E-05以“工具声称产出文件、独立采样未发现输出”验证。通用网络absence证明仍不支持，不将此描述为网络全覆盖或生产隔离。

补充：声明资源和效果类型必须匹配Engine动作投影，拒绝把既有动作引用用于其他效果要求。补充该检查后重新完成全Go vet/race和四平台编译；新增资源错配断言单独通过HTTP race后提交。

### 2026-09-08：撤销后历史效果与来源到期并发验收

- 扩展 HTTP E-05 测试：全局 Intent 撤销后仍可收录历史工具声明并完成独立文件采样、计算冲突；同一 session 的新 Decide 必须 deny/intent_revoked，即使 warn 模式也不恢复授权。
- 扩展 TestConcurrentProvenanceIssueDecideAndRevoke 为三模式 × revoke/expiry。每种组合16个并发签发者/决策调用者，先证明合法来源可用；过渡阶段允许符合时间快照的结果，终态同步后每人4次必须 hard deny、无 advisory，撤销码与到期码分别校验。使用原子测试时钟，无真实时间sleep或共享时钟数据竞争。新增192次到期后拒绝断言。
- §89 对应：Effect原子重复、冲突与重开见 TestStoreAtomicIncidentRetryConflictAndRecovery；容量见 TestStoreCapacityAndInterruptedPublication / TestGraphNodeAndEdgeCapacityBoundaries；图重开见 TestGraphRejectsTrustAndSourceLaundering；实际decision→pending→SIGKILL→effect恢复和回执验证见已归档nightly-693641d及recovery_fixture。旧nightly只作为该恢复路径的基线证据。
- §85核验发现两个剩余细项：跨task引用安全拒绝已实现，但返回not_found而非模板指定scope_mismatch；物理Assertion文件篡改还缺专门回归。保留为待处理，未用其他通过测试替代要求。

P07本批已补齐：TestPersistedAssertionTamperingFailsAfterRestart 在私有临时状态实际改写已签发文件的content_digest或signature，重开Store后均要求provenance_signature_invalid；先验证未篡改记录可读。focused race与provenance vet通过。四个关联包provenance/effectevidence/receipt/server的race全部通过（/tmp/siq-revocation-expiry-audit-race.log），receipt/server vet通过。无生产实现变更。

远端功能基线1f10e9c的ci 34189914689与runtime-security 34189914681均success；本批新增测试尚待推送后的新CI，不用该基线代替新增测试证据。
