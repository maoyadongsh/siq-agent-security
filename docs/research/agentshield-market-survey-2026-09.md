# AgentShield 外部市场调研：同类产品功能与可借鉴方法论

- 日期：2026-09-03
- 范围：Skill / MCP / Agent 运行时安全（扫描、准入、最小权限、沙箱、回执）
- 用途：给 `siq-agent-security` 上的 **AgentShield · Skill 门禁官** 定方案，不另起产品线
- 结论先说：市面上没有和 AgentShield 完全同构的产品。扫描器很多、MCP 网关很多、沙箱很多、企业态势很多——**把「发现 → 声明能力 → 签发最小权限 → 沙箱执行 → 每次工具调用出回执」串成一条本地可运行闭环的，几乎没有。** 这正是黑客松作品该打的点。

---

## 0. 怎么读这份调研

同类产品按 **六条边界** 卖（PipeLab 2026 买方地图）。买错边界会买到「模型网关」却解决不了「Skill 把 `.env` POST 出去」。AgentShield 只覆盖其中四条，且必须本地、可离线、挂在 OpenShell + Hermes 上：

| 边界 | 市场在卖什么 | AgentShield 现场做不做 |
| --- | --- | --- |
| 1. 模型 / API 网关 | LiteLLM、TrueFoundry、SIQ Gateway | **轻做**：模型路由进 grant（本地 Nemotron 放行，云端 StepFun 经脱敏 broker），不重做 Gateway |
| 2. MCP / 工具网关 | Solo.io agentgateway、Docker MCP Gateway、mcp-gate、MCPKernel | **做工具拦截，不做成通用 MCP 代理**：Hermes `pre_tool_call` / `post_tool_call` |
| 3. 非人身份 (NHI) | Aembit、Astrix、SPIFFE | **不做**：租户身份仍走 IAM；现场用仓内信任根 |
| 4. 应用 / 平台治理 | Zenity、Cisco AI Defense、Prisma AIRS | **轻做盘点页**：本机资产清单，不是企业 SaaS 态势 |
| 5. 运行时隔离 | OpenShell、E2B、Daytona、gVisor、Firecracker | **用 OpenShell，不另起沙箱** |
| 6. 出网内容防火墙 | Prompt Security、Pipelock、Claude/Codex 域名 allowlist | **做网络策略 + 回执里的 DLP/污点，不做独立 HTTPS MITM** |

PipeLab 的原话值得当成设计约束：**「多数认真的 Agent 部署至少需要三条边界：身份管谁、运行时管在哪、出网管什么。买一个产品不等于买齐六条。」** AgentShield 的叙事应是「四 Skill 覆盖 2/4/5/6 的本地最小闭环」，而不是「取代 SkillSpector / Prisma」。

---

## 1. 市场地图：谁在干什么

### 1.1 Skill 供应链（安装前）

这是和 `skill-admission` 最近的一层。NVIDIA 自己已经把「Verified Skills」做成官方治理故事——黑客松评委几乎一定见过。

| 产品 | 做什么 | 不做 / 弱点 |
| --- | --- | --- |
| **NVIDIA SkillSpector** | 安装前扫描 Skill（目录 / zip / git / 单文件）。约 68–71 条模式、17 类：注入、外传、提权、供应链、过度代理、工具误用、MCP 投毒、污点、YARA。默认静态；可选 LLM 语义（描述 vs 行为）。OSV.dev CVE + 离线回退。输出终端 / JSON / Markdown / **SARIF**。有 baseline 抑制误报、分析资源上限 fail-closed。 | 扫描 ≠ 授权 ≠ 运行时拦截。语义层要出网 LLM。官方文档 triage 明确：**能力少报应更新权限声明，而不是一律隔离。** |
| **NVIDIA SkillEvaluator** | 三层：T1 静态/安全/PII/Unicode/脚本（含 SkillSpector）；T2 去重；T3 有/无 Skill 的 live 评测，出 `BENCHMARK.md`。 | T3 要跑 Agent，现场演示成本高。 |
| **NVIDIA Verified Skills** | 流水线：编目 → 扫描 → 评测 → **分离签名 `skill.oms.sig`（OpenSSF Model Signing）** → **Skill Card**。签名覆盖目录每个文件。验证用 `model_signing verify` + `nv-agent-root-cert.pem`。 | **生成 Card ≠ 签名 ≠ 批准发布。** 官方 skill-card-generator 自己写了这句。 |
| **Snyk Agent Scan**（原 Invariant MCP-Scan） | **先发现再扫描**：本机 Claude/Cursor/Gemini/Windsurf 配置里的 harness、MCP、Skill。威胁：tool poisoning、rug pull、shadowing、toxic flow、恶意 Skill。有 proxy 运行时模式。0.4 起扫 Skill。 | **扫 MCP 配置会启动 stdio 服务器**（执行 config 里的 command）。官方警告必须在沙箱里扫。输出 schema 仍实验性。 |
| **MCP-Shield**（独立项目） | 规则扫描：隐藏指令、shadowing、外传通道、跨源。可选 Claude 加深分析。`--identify-as` 测服务是否按客户端 ID 换行为（bait-and-switch）。 | 点扫，无运行时强制。 |
| **Hermes `skills_guard.py`**（仓内只读参考） | 约 120 条 regex + symlink/二进制/体积。仅 `hermes skills install/audit/publish` 触发；**`~/.hermes/skills` 本地加载不扫**。把 `allowed-tools` 标成 high privilege_escalation，但加载器**不执行**该字段。 | 误报模式与我们对 NVIDIA 349 个官方 Skill 的实验一致：有模式 ≠ 该隔离。 |

### 1.2 MCP / 工具运行时（调用时）

这是和 `runtime-receipt` + `least-privilege-grant` 最近的一层。

| 产品 | 做什么 | 方法论要点 |
| --- | --- | --- |
| **MCPKernel** | Agent Host 与 MCP 之间的内核：策略 → 污点 → 跨工具 DLP → 沙箱执行 → **确定性信封（DEE）+ Sigstore** → 只追加审计。YAML `allow/deny/audit/sandbox`。映射 OWASP ASI。 | 六步流水线可直接当 receipt 的阶段名。`PII in → HTTP out = block` 是 toxic flow 的工程化。 |
| **mcp-gate** | `tools/call` 代理：允许 / 拒绝 / **等人批** / **改写参数脱敏**。哈希链审计。fail-closed。映射 NIST AI RMF + OWASP Agentic。启发式扫参数里的注入、密钥、路径穿越。 | 「四种处置」比二元 allow/deny 更适合演示。 |
| **MCP Seatbelt 一类 default-deny 代理** | JSON-RPC 默认拒绝，未登记工具直接挡。 | 闭世界 allowlist = Hermes `platform_toolset_modes: allowlist` 已经在走的路。 |
| **Solo.io agentgateway** | K8s/独立 MCP 网关：JWT（JWKS）+ CEL 按 claim 授工具。 | 身份网关，不是 Skill 门禁。现场不搬 K8s。 |
| **Docker MCP Gateway / Catalog** | 容器跑 MCP、签名目录、SBOM。 | 供应链层，可对标 OMS；现场用仓内 Ed25519 即可。 |
| **Claude Code permissions + sandbox + hooks** | `deny > ask > allow`；用户级 deny **项目不能覆盖**；permission-mode（default / acceptEdits / plan / bypass）；Bash 进 OS sandbox 后可自动批准；hooks 可编程拦调用。`strictAllowlist` 出网 fail-closed。企业 `managed-settings.json` 用户改不掉。 | **「权限决定能不能调，沙箱决定调了能走多远」**——和 OpenShell 静态段 vs 动态网络、Hermes allowlist vs 插件拦截完全同构。 |
| **OpenAI Codex enterprise** | `requirements.toml` **覆盖用户 config**。MCP allowlist 必须 **name + identity（command 或 url）** 双匹配；空表 = 禁用全部 MCP。沙箱模式 `read-only` / `workspace-write` / `danger-full-access`，MCP 继承。保护 `.git` / `.agents` / `.codex`。 | 防「改个名字绕过 allowlist」。SHA-256 钉死二进制仍是公开缺口（Issue #15814）。 |

### 1.3 运行时隔离（进程 / 文件系统 / 网络）

| 产品 | 隔离强度 | 和现场关系 |
| --- | --- | --- |
| **NVIDIA OpenShell** | 静态：filesystem / Landlock / process，**创建时锁定**；动态：`network_policies` 可 `policy set` 热更新。默认拒绝出网。binary+host 双匹配；REST 可 L7 method/path。`inference.local` 走推理路由不是 OPA。Landlock best-effort 失败发 OCSF DetectionFinding。 | **执行后端已选定。** 仓内实测：网络动态闭环可跑；`create_generation` 在 CLI 路径仍抛错 → 文件系统策略不能热下发。现场只做网络热更新 + 静态沙箱创建。 |
| **E2B** | Firecracker microVM，冷启动快，为「跑一段代码」设计 | 云沙箱，不是 DGX 本地 Skill 门禁 |
| **Daytona** | 持久开发工作区 + 网络策略 | 长会话 IDE，不是一次分析任务 |
| **gVisor / Modal** | 用户态内核，适合多租户容器 | OpenShell 已覆盖 syscall/Landlock 故事 |
| **Firecracker / Kata** | 硬件虚拟化，最强隔离 | Spark 上不值得为黑客松再叠一层 VMM |

行业共识（Northflank / Spheron 2026）：不信任代码用 Firecracker；自有代码用 gVisor；信任代码才用普通容器。AgentShield **不重做沙箱**，只证明「谁有资格进已有沙箱、带什么策略进去」。

### 1.4 企业态势 / 扫描平台（盘点层）

| 产品 | 借鉴点 | 不要学什么 |
| --- | --- | --- |
| **Snyk Agent Scan 发现器** | 从各家 config 自动找出 Agent / MCP / Skill | 不要为了扫 MCP 去执行第三方 command |
| **Zenity** | 企业内 MCP 与 owner 绑定 | SaaS 控制台不是参赛形态 |
| **Palo Alto Prisma AIRS**（2026-03 加 Agent 扫描） | Agent 代码 + MCP + 路径扫描进现有安全栈 | 体积和许可都不适合现场 |
| **Cisco AI Defense** | 运行时拦 MCP 请求 | 同上 |
| **Cisco MCP Scanner** | 语义分析工具定义，不只正则 | 可选引擎，离线默认仍用规则 |

### 1.5 威胁框架（不是产品，但是共同语言）

评委和安全评测会用这些编号。Skill card / receipt / 演示脚本应对上，而不是发明第六套分类。

**OWASP Top 10 for Agentic Applications 2026（ASI01–ASI10）**

| ID | 风险 | AgentShield 对应控制 |
| --- | --- | --- |
| ASI01 Goal Hijack | 目标被文档/工具描述改写 | admission 硬隔离欺骗用户 / 提示注入 |
| ASI02 Tool Misuse | 工具组合、过度权限 | grant 最小权限 + receipt 参数校验 |
| ASI03 Identity / Privilege Abuse | 委托身份、权限扩散 | permission-fact 五态；模型不得写 `effective` |
| ASI04 Supply Chain | 登记、签名、钉版本 | 内容哈希 + 仓内 Ed25519；OMS 路线图 |
| ASI05 Unexpected Code Execution | 任意代码 / 出网 | OpenShell + default-deny 网络 |
| ASI06 Memory Poisoning | 污染记忆 | 现场不做 Memory 产品；只拒绝写系统路径 |
| ASI07 Inter-Agent Comms | Agent 互信 | 单 Agent 演示，不承诺 |
| ASI08 Cascading Failures | 故障放大 | lease/TTL、越权即停 |
| ASI09 Human-Agent Trust | 骗过审批 | 回执必须人能读；Card ≠ 批准 |
| ASI10 Rogue Agents | 行为漂移 | observed vs effective 差异告警 |

**Invariant Toxic Flow Analysis**：先建工具流图（信任级、数据敏感度、是否外传槽），再给「可能的有毒路径」打分。典型 **lethal trifecta**（Simon Willison）：私有数据 + 不可信内容 + 外传通道，三者同时具备才真正危险。GitHub MCP 漏洞就是这条。

**Rug pull / Tool pinning**：一次扫描不够。对 tool name+description+schema 做哈希，变更必须重新批准（Trail of Bits 的 trust-on-first-use）。Codex 的 name+identity 双匹配是同一思想在配置层的版本。

---

## 2. 可借鉴的方法论（按四个 Skill 拆）

### 2.1 `agent-asset-inventory` — 先发现，再谈风险

市面共识：**看不见的资产无法授权。** Snyk Agent Scan 的产品入口就是「扫你机器上已经装了什么」，不是先给风险分。

**借鉴**

1. **多 harness 配置发现**：Claude / Cursor / Gemini / Windsurf / Hermes `config.yaml` + `skills/` + MCP json。仓内 Hermes connector 已盘 profile / `SOUL.md` / toolsets，但 **不盘 `skills/`**——这是 inventory 必须补的洞。
2. **Connector 合同已比市场严格**：`describe` / `plan_scan` / `collect`、脱敏、孤儿 evidence 拒绝、`.env` 只出 `secret_ref`。保持这个纪律，不要为了「扫得全」去读密钥正文。
3. **Owner 绑定**：Zenity 把 MCP 挂到人和 Agent。演示里每条资产要有 `authority` + `evidence_ids`，不能只有文件名。
4. **扫描器自身要进沙箱**：Snyk 明确写了「分析 MCP 会执行 command」。inventory 若去连 MCP，必须在 OpenShell 里连，或只读配置、不启动服务器。

**不抄**

- 不要做成跨企业 SaaS CMDB。
- 不要为了发现去执行不可信 MCP。

### 2.2 `skill-admission` — 发现能力，而不是「有正则就隔离」

这是 NVIDIA 官方文档和我们对 349 个官方 Skill 实验 **共同指向的设计**。

SkillSpector / SkillEvaluator 的 triage 表：

| 发现类型 | 官方建议动作 |
| --- | --- |
| Critical / High | 发布前修复或正式接受风险 |
| 隐藏指令 / 工具投毒 | 删隐藏内容后再发 |
| **少报的能力（underdeclared）** | **更新权限声明，或删掉该行为** |
| 已知漏洞依赖 | 升级、钉版本、或书面接受 |
| 描述与行为不符 | 改描述或改代码 |

我们对 NVIDIA 官方目录的扫描：`admit 49 / admit_with_conditions 259 / quarantine 37（10.6%）`，隔离几乎全是误报（文档里的 “do not tell the user”、占位 `hf_xxxx`、references 里演示 `.env`）。**84 个官方 Skill 正经使用 `allowed-tools`。** Hermes guard 把该字段当提权，是错的产品语义。

**必须借鉴**

1. **决策表拆成两列**：硬隔离（欺骗用户、读密钥外传、提示注入、完整性失败）vs **升级为 `declared` 权限事实**（sudo、curl\|sh、出网、写路径——官方 Skill 里这是正常需求）。
2. **静态优先、LLM 可选**：SkillSpector 默认 `--no-llm`。Spark 现场默认离线规则包（仓内已有 Ed25519 签名 `threat_rules.v1.json`）。语义层若做，走本地 Nemotron，失败则规则+人工，符合 ADR-003。
3. **Unicode / 同形字 / HTML 注释 / 零宽字符**：SkillSpector TP1/TP2。现有规则包几乎没有，admission 应加一小撮确定性检查，不必 71 条全抄。
4. **内容哈希钉死 + 变更重审**：防 rug pull。对 SKILL.md + scripts 算 hash，写入 HubLock 一类记录。现场不必接 Sigstore。
5. **SARIF / JSON 双输出**：方便评委脚本和以后接 CI。
6. **Skill Card 与签名分离**：卡上写所有权、风险、依赖、验证状态；生成卡不能当成已签名或已批准（NVIDIA 原话）。
7. **资源上限 fail-closed**：SkillSpector 对包大小、嵌套产物、finding 数量设天花板。超限 = 拒绝安装，不是静默截断后放行。
8. **误报基线**：官方扫描器有 baseline 抑制。我们已有 `docs/detection-baseline.md` 的诚实召回/误报口径——admission 必须带「官方 Skill 回归集」，避免再把 NVIDIA 自己的 Skill 隔离掉。

**不要做的**

- 不要在现场重写 SkillSpector。可以 **可选调用** `skillspector --no-llm` 作为第二引擎，主引擎仍是仓内规则 + frontmatter/`allowed-tools` 解析。
- 不要把 `allowed-tools` 当越权。它是 **declared**，Hermes 闭世界 allowlist 才是 **effective**。价值在算差异并让人签核。
- 不要依赖出网 LLM 才能出裁决。

### 2.3 `least-privilege-grant` — 声明与生效必须分家

市面产品大多只有「策略 YAML」或「allow 数组」，没有五态。这是仓内 ADR-004 相对市场的真正差异，应强化而不是抹平。

**借鉴**

1. **Claude：deny 覆盖 allow，且更高层 deny 不可被项目放行绕过。** grant 编译时重叠必须输出 `overlap_conflicts`（设计文档 §12.4），禁止静默并集。
2. **Codex：管理面约束覆盖用户配置。** 对标 `desired-policy` 审批后才能变 `effective`。用户/模型不能把 `bypassPermissions` 写进生效集。
3. **MCP allowlist 双匹配**：工具名 + 身份（二进制路径或 URL）。只匹配名字会被改名绕过。OpenShell 的 binary+host 双匹配已经是这个思想。
4. **Default-deny**：未出现在 grant 里的工具/域名/路径 = 拒绝。与 MCP Seatbelt、OpenShell 默认拒绝出网一致。
5. **权限 vs 沙箱分工**（Claude 官方）：allowlist 回答「能不能调用 `web_extract`」；OpenShell 回答「这次调用能碰到哪些盘、哪些网」。grant 应同时产出：Hermes toolset allowlist **和** OpenShell `DesiredPolicy`。
6. **渐进强制**：仓内已有 `audit_only → warn → block` 只升不降。演示用 block；评测/金丝可用 warn。openshell-cli 目前只支持 block，文档要诚实。
7. **静态 vs 动态**：OpenShell 文件系统创建时锁定，网络可热更新。grant 不要承诺「改完 fs 策略立即生效」——现场只演示网络段 `policy set` + 读回 revision。
8. **四种处置**（mcp-gate）：allow / deny / hold / redact。grant 对「需要但高风险」的能力用 hold（人签）而不是直接 effective。

**不要做的**

- 不要让 SkillSpector 或任何 LLM 分类结果直接变成 `effective`（ADR-003）。
- 不要经 CLI 调 `create_generation` 假装 fs 策略已部署。
- 不要做 Solo.io 那种集群级 JWT/CEL 网关。

### 2.4 `runtime-receipt` — 每次调用都要留下可重放证据

扫描是点时间；rug pull 和 toxic flow 发生在批准之后。市场已把「运行时信封」做成产品核心（MCPKernel DEE、mcp-gate 哈希链、Pipelock 内容检查）。

**借鉴**

1. **拦截点在 Host 与工具之间**，不是事后读日志。Hermes 插件 `pre_tool_call` 返回 `{"action":"block","message":...}` 已经能挡；`post_tool_call` 做观测。这比再做一层 MCP 代理更贴现场。
2. **污点 + 跨工具 DLP**：参数里出现 secret/PII 标签后，后续 `http` / `send_message` / webhook 直接拒绝。这是 toxic flow 的最小可演示版，不必上 eBPF。
3. **确定性信封**：输入哈希、输出哈希、策略 revision、sandbox id、模型 key、时间。MCPKernel 用 Sigstore；现场用仓内 Ed25519 签 receipt 即可。评委能 `verify` 一条回执。
4. **哈希链 / 只追加**：mcp-gate 的审计链。receipt 文件 append-only，演示「越权被拒」那条红回执不能被模型改写。
5. **对人可读**：NVIDIA Skill Card 原则——弱风险陈述（「模型可能错」）换成可执行缓解（「不得写出配置的输出目录」）。红色回执要写清：哪个 tool、想碰哪条路径/域名、哪条 grant 拒绝、哪条 evidence。
6. **Lethal trifecta 运行时检查**：同一 session 若同时具备「读了私有挂载」「摄入了不可信 Skill/网页」「打了外网」，receipt 升为 high 并默认 block 外传。这比单条 regex 外传规则更接近真实攻击。
7. **参数红action 再放行**（mcp-gate redact）：演示「不是整次失败，而是剥掉密钥再走」——可选，第二优先；第一优先是 block。

**不要做的**

- 不要做全流量 HTTPS MITM（边界 6 的商业防火墙）。OpenShell 网络策略 + 工具参数检查足够演示。
- 不要把 receipt 做成无法离线验证的云审计。

---

## 3. 一张总表：市场功能 → AgentShield 落点

| 市场功能 | 代表产品 | 落哪个 Skill | 现场形态 | 优先级 |
| --- | --- | --- | --- | --- |
| 本机发现 harness / Skill / MCP | Snyk Agent Scan | inventory | 读配置+目录，不启动 MCP | P0 |
| Frontmatter / `allowed-tools` 解析 | NVIDIA 官方 Skill 惯例 | admission | declared 事实 | P0 |
| 静态威胁规则 + 签名规则包 | 仓内 `threat_rules.v1` / SkillSpector | admission | 复用+补 Unicode/欺骗类 | P0 |
| 少报能力 → 补权限而不是隔离 | SkillEvaluator triage | admission → grant | 决策表改写 | P0 |
| 内容哈希 / tool pinning | Invariant、Codex identity | admission | hash 入证据 | P0 |
| Skill Card | NVIDIA Trustworthy-AI | admission 产物 | 人读；≠ 批准 | P0 |
| Default-deny + 闭世界工具表 | Seatbelt、Hermes allowlist | grant | Hermes toolset | P0 |
| 网络策略热更新 + 读回 | OpenShell `policy set` | grant | 只演示网络段 | P0 |
| deny 覆盖 allow / 管理面不可绕过 | Claude、Codex requirements | grant | 五态+审批 | P0 |
| pre_tool_call 阻断 | Claude hooks、Hermes 插件 | receipt | 越权红回执 | P0 |
| 跨工具 DLP / toxic flow | MCPKernel、Invariant TFA | receipt | 最小规则：secret→http | P1 |
| 确定性签名信封 | MCPKernel DEE、OMS | receipt | 仓内 Ed25519 | P1 |
| SARIF / CI | SkillSpector | admission | JSON 即可，SARIF 可后补 | P1 |
| 可选第二扫描引擎 | SkillSpector `--no-llm` | admission | 包装调用，非重写 | P1 |
| OMS / Sigstore | NVIDIA Verified、MCPKernel | 路线图 | 训练营若发工具包再切 | P2 |
| Live with/without Skill 评测 | SkillEvaluator T3 | 自己的四个 Skill | `evals/` 回归，不必 T3 全套 | P2 |
| 企业 NHI / JWT MCP 网关 | Solo.io、Aembit | 不做 | — | — |
| Firecracker / E2B 云沙箱 | E2B | 不做 | 已有 OpenShell | — |
| 出网内容 MITM 防火墙 | Pipelock、Prompt Security | 不做 | 网络 allowlist 代替 | — |

---

## 4. 差异化：评委听得懂的一句话

> SkillSpector 告诉你「这个 Skill 像不像恶意的」。  
> Claude/Codex 告诉你「这个 Agent 能不能调这把工具」。  
> OpenShell 告诉你「进了沙箱之后手能伸多远」。  
> **AgentShield 把三句话接成一条本地流水线，并且用 permission-fact 五态保证：扫描结论和模型建议永远不能自己变成生效权限。**

市场空白具体有三处：

1. **扫描器停在 Finding，不签发策略。** SkillSpector 没有 OpenShell compiler。
2. **网关管 MCP，不管 Skill 安装与 `allowed-tools` 声明差。** agentgateway 不读 SKILL.md。
3. **沙箱不管「谁有资格被放进来」。** OpenShell 假定策略已经是对的。仓内 `create_generation` 还不能把 fs 策略热下发——所以作品必须把「策略从哪来」讲清楚，而不是假装五域都能热更新。

---

## 5. 对仓内合同的约束（借鉴也不能破坏）

下列不变量继续有效；市场功能若冲突，改产品叙事，不改不变量。

| 不变量 | 来源 | 对借鉴的限制 |
| --- | --- | --- |
| 模型输出不能创建 `effective` | ADR-003 / ADR-004 | SkillSpector LLM 层、分类器、演示脚本都只能产 `inferred`/`declared` |
| 每条结论要有 `evidence_ids` | ADR-003、evidence schema | 扫描命中必须落 evidence，禁止「规则命中但无证据」的隔离 |
| 五态不可混用 | permission-fact schema | `allowed-tools` → declared；Hermes allowlist 读回 → effective；运行拦截 → observed |
| Secret 明文不落库/不进日志 | 仓库指南 | inventory 继续 `secret_ref`；receipt 必须 redaction |
| 不长期 Fork OpenShell | ADR-005 | 不把 E2B/gVisor 补丁打进 OpenShell |
| 生产不用 SQLite 冒充 | 仓库指南 | 现场演示可用仓内已有 dev 开关，文档标明 |
| `create_generation` 不可用则 fs 不得装成 effective | round3/4 审计 | grant 对 filesystem 保持 unknown 或静态创建，禁止假 effective |

现有检测基线也要带到 admission：规则包 25 条召回是「冒烟回归」不是野外能力；`threat-net-hardcoded-c2` 不得自动隔离；通用 HTTPS POST 目前 **不算** exfil（只认 webhook.site / Discord / Slack / ngrok）。若 receipt 要拦「读 `.env` 后任意 HTTPS」，必须 **新增污点规则**，不能指望旧规则包。

---

## 6. 建议写进方案的 12 条（按实现顺序）

1. **Admission 决策表**：硬隔离 vs 升级为 declared 事实（对标 SkillEvaluator underdeclared）。
2. **解析 `allowed-tools` + frontmatter**：官方 84 个 Skill 的真实用法是声明，不是越权。
3. **Inventory 补 `skills/` 与 MCP 配置只读发现**：对标 Snyk 发现器，但不执行 server command。
4. **内容哈希钉死 + 变更重审**：对标 tool pinning / rug pull。
5. **Skill Card 模板**：NVIDIA 最小卡；页脚写「本卡不是签名、不是批准」。
6. **Grant = Hermes allowlist ∩ OpenShell DesiredPolicy**：对标 Claude「权限 + 沙箱」双层。
7. **只演示网络策略热更新 + revision 读回**：对标 OpenShell 动态段；fs 用静态沙箱。
8. **Default-deny + deny 覆盖 allow**：对标 Seatbelt / Claude / Codex。
9. **Hermes 插件出签名回执**：对标 MCPKernel DEE，签名用仓内 Ed25519。
10. **Session 级 lethal trifecta**：私有数据 ∩ 不可信输入 ∩ 出网 → block。对标 Invariant TFA 的最小实现。
11. **官方 Skill 回归集**：用 NVIDIA 目录防误隔离，作为评委可跑的负向评测。
12. **路线图写明 OMS / Sigstore / SkillSpector 第二引擎**：训练营若发工具包可切换，不绑死现场。

---

## 7. 来源（2026-09-03 检索）

- NVIDIA Skills 文档：[Verified Skills](https://docs.nvidia.com/skills)、[Scan with SkillSpector](https://docs.nvidia.com/skills/scanning-agent-skills)、[Skill Cards](https://docs.nvidia.com/skills/skill-cards)、[Release checklist](https://docs.nvidia.com/skills/release-checklist)、[SkillEvaluator T1](https://docs.nvidia.com/skills/skillevaluator/tier1-validation)
- NVIDIA 技术博客：*NVIDIA-Verified Agent Skills Provide Capability Governance for AI Agents*
- [NVIDIA/SkillSpector](https://github.com/NVIDIA/SkillSpector)
- [Snyk Agent Scan / Invariant MCP-Scan](https://github.com/invariantlabs-ai/mcp-scan)；Invariant: Tool Poisoning、Rug Pull、[Toxic Flow Analysis](https://invariantlabs.ai/blog/toxic-flow-analysis)
- [MCP-Shield](https://github.com/riseandignite/mcp-shield)
- [MCPKernel](https://github.com/piyushptiwari1/mcpkernel)（策略 / 污点 / DLP / DEE / Sigstore）
- mcp-gate（`tools/call` 代理、哈希链审计、NIST/OWASP 映射）
- Claude Code 官方：[Permissions](https://code.claude.com/docs/en/permissions.md)、[Sandboxing](https://code.claude.com/docs/en/sandboxing.md)
- OpenAI Codex：[Managed configuration / requirements.toml](https://developers.openai.com/codex/enterprise/managed-configuration)
- Solo.io agentgateway JWT + MCP RBAC 文档
- PipeLab：[六条安全边界](https://pipelab.org/learn/ai-agent-security-categories/)、[2026 工具图](https://pipelab.org/blog/best-ai-agent-security-tools-2026/)
- OWASP *Top 10 for Agentic Applications 2026*（ASI01–ASI10）
- 沙箱谱系综述：amux / Northflank / Spheron（E2B、Daytona、gVisor、Firecracker）
- 仓内：`packages/contracts/`、ADR-003/004/005、`docs/detection-baseline.md`、`docs/compatibility.md`

---

## 8. 诚实边界

- 商业产品（Prisma AIRS、Cisco AI Defense、Zenity）的内部规则集无法复现，上表只采用公开文档与评测文。
- SkillSpector 文档在「68 模式」与 README「71 模式」之间有出入，引用时写范围而非钉死数字。
- MCPKernel / mcp-gate 是早期开源内核，成熟度低于 Claude/Codex/NVIDIA 官方栈；借鉴的是流水线形状，不是把依赖打进作品。
- 本调研不评估价格或采购；只服务黑客松可运行闭环与仓内不变量。
