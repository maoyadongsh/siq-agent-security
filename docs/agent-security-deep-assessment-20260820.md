# 智能体安全管控平台深度评估与优化建议（对标杀毒范式）

- 评估时间：2026-08-20（Asia/Shanghai）
- 审计仓库：`siq-agent-security`（`main`，HEAD `cf5fbef`）
- 评估视角：硅谷资深 AI 全栈工程师 + AI 智能体安全专家；方法论借鉴杀毒软件「扫描 → 发现 → 识别 → 检测 → 管控 → 审计」六阶段
- 与 [agent-security-audit-20260820-153735.md](agent-security-audit-20260820-153735.md) 的关系：本次为独立深度复核——三处 P0 关键结论重新亲自读码确认，补充 OpenShell 二次开发专项评估、双轨目标架构与分期改造路线
- 已确认方向：四项能力（发现广度 / 恶意脚本检测 / 风险评分 / 权限行为管控）全部为优先投入；长期执行底座走**双轨并行**（OpenShell 沙箱 + Host Sensor/OS 强制）
- 本次交付：仅评估报告 + 优化建议，未修改产品源码

## 一、执行摘要（总体判断）

**一句话结论**：本项目当前不是杀毒软件、不是 EDR，而是一个**「智能体资产发现 + 治理状态风险评估 + 策略审批治理 + 局部受管运行时（OpenShell）策略下发」的控制面原型**。它的审计治理层（同事务审计、SoD、fail-closed、签名信任链）是国内少见的高质量工程；但「扫描所有智能体、识别风险高低、发现恶意脚本、精准管控权限行为」这四项产品承诺中，前两项只有窄覆盖，后两项基本缺失。

| 杀毒范式阶段 | 产品承诺 | 现状（成熟度） | 一句话证据 |
| --- | --- | --- | --- |
| 扫描 Scan | 扫描所有智能体 | **2/5** | 仅 4 类 Connector；docker 只扫带 `siq.agent=true` 标签的容器；无 piagent/workbudy/dify/进程/MCP |
| 发现 Discover | 全量资产盘点 | **3/5** | 候选→确认→纳管状态机完整，但任务领取非原子、AgentInstance 模型是死路径 |
| 识别 Classify | 识别是什么智能体 | **2/5** | 名称关键词置信度（0.9/0.6/0.3），framework 字段根本没用上 |
| 风险 Risk | 识别风险高低 | **2/5** | 规则引擎只查治理状态（无 owner/心跳过期/共享凭据），不分析内容与行为 |
| 恶意检测 Detect | 发现恶意脚本 | **0.5/5** | Connector 不读脚本内容、无 YARA/AST/动态分析；评测集量的是「是不是智能体」不是「是不是恶意」 |
| 权限管控 Control | 权限精准管控 | **2/5** | 网络策略动态闭环可跑；文件/进程静态策略因 `create_generation` 抛错而不可部署 |
| 行为管控 Behavior | 行为精准管控 | **1/5** | 无真实行为事件流、无阻断证据、无隔离/取证/恢复 |
| 审计治理 Audit | 全过程可审计 | **3.5/5** | 同事务审计 + Outbox + SoD + fail-closed 门禁，设计完整、个别绑定仍需加固 |
| 跨平台 Any OS | 任意系统安装运行 | **1/5** | 明显依赖 Linux 命令 + OpenShell 沙箱 + Go 子进程 |

**给管理层的判断**：工程地基是对的，应该继续走「统一智能体资产 + 风险 + 策略 + 审计控制平面」方向，OpenShell 作为首个受管运行时后端也合理。但在「恶意脚本检测引擎」和「宿主机行为管控」落地前，产品对外只能定位为**「智能体资产发现、风险治理与受管沙箱策略控制平台」**，不能宣称具备杀毒/EDR 级检测与全平台管控能力——否则是产品安全承诺偏差，客户按承诺采购后必出事故。

## 二、值得保留的资产（不推倒重来）

1. **安全地基哲学**：证据链 + 模型非权威 + fail-closed（`app/config.py:51-135` 生产门禁强制 PostgreSQL/OIDC/签名密钥/CORS 白名单）。这是正确的安全起点。
2. **合同优先**：`packages/contracts/` 6 份 JSON Schema + connector-protocol.v1.md 是唯一事实源，跨 Python/Go 共享，破坏性变更先升版本再同步实现。
3. **Edge 信任模型**（ADR-002）：注册码一次性 + 短 TTL + 只存哈希、任务 Ed25519 验签（`edge/agent/task.go:40-78`，fail-closed）、吊销即时在线校验、证据批次 + 逐条双重验签。
4. **策略治理闭环**：`draft→…→effective` 状态机 + SoD（提案≠审批，break_glass 不豁免）+ enforcement_mode 渐进档位（降级需 high_risk 变更单）+ 漂移检测（`app/drift.py` revision 比对 fail-closed）。
5. **受限子进程 Connector 协议**（ADR-008）：NDJSON、60s/8MiB 限额、脱敏规则（`edge/agent/redact.go:40-50`）、.env 永不读取、payload_ref 为 null 只出 content_hash（内容不出机）。
6. **OpenShell 接入方向正确**（ADR-005/009）：版本化 adapter + 能力探测而非版本假设 + patch 治理，v0.0.104 已闭环实测网络策略热更新。
7. **Web 控制台的诚实边界**：Agent 详情的 enforce 徽标区分「已强制（OpenShell）」vs「声明未强制」（`apps/web/src/pages/AgentDetailPage.tsx:222-232`）——没有把「规划」伪装成「已执行」。
8. **威胁模型可回链**：T1–T22 每行威胁能指到控制与负向测试，未闭环项显式列 TODO。

## 三、对标杀毒范式的能力矩阵深度评估（文件级证据）

### 3.1 扫描 Scan——覆盖面不足，且不是「扫描」

- **只有 4 个 Connector**（`app/schemas.py:175` `ConnectorName = Literal["hermes","openclaw","docker","directory"]`）：hermes 扫 `~/.hermes/profiles/*`、openclaw 扫 `openclaw.json` 的 `agents.list`、directory 扫指定目录下的 `SOUL.md`/`agent.yaml`、docker 扫**带 `siq.agent=true` 标签**的容器（`connectors/docker/docker.go:244`）。
- **无** piagent / workbudy / dify / Kubernetes / systemd / 进程列表 / MCP server 任何实现（全仓库 grep 零命中，schema 里声明的候选来源是空壳）。
- **关键缺陷：docker Connector 只扫打标签的容器**。客户环境里没打这个标签的智能体容器会被静默漏掉——这正是「影子智能体盘点」要消灭的盲区，却在发现源上先制造了盲区。
- **Connector 不扫描「内容」**：所有 Connector 只提取元数据 + sha256 内容哈希，`payload_ref` 恒为 null（`connectors/hermes/hermes.go:11-12`）。这意味着连最基础的**杀毒式签名匹配（对已知恶意脚本指纹）都无法工作**——哈希只用于去重和证据，没有指纹库可比对。

### 3.2 发现 Discover——状态机扎实，但身份模型断裂 + 任务领取非原子

- 候选生命周期 `candidate→needs_review→confirmed→managed`（旁路 `dismissed`）完整，`smart_scan` 按租户配额生成签名任务（`inventory.py:41-103,106-175`）。
- **断裂点 1：AgentInstance 模型是死路径**。`app/models.py:125-137` 定义了 `AgentInstance`（runtime 注释含 `pi`/`embedded`），但**全仓库没有任何写入它的代码**。发现→实例→运行时目标的身份链条在「实例」这一环断掉了，导致部署只能指向自由字符串。
- **断裂点 2：候选入账即丢字段**。Edge 上传的 candidate 带 `artifact_digest`/`attributes`，但 `inventory.py:350-358` 只存 name/framework/status/evidence_ids——**资产指纹和特征被丢弃**，后续做基线比对、信誉、指纹变更检测没有数据。
- **断裂点 3：任务领取非原子**。`environments.py:201-223` 的 `edge_fetch_tasks` 是普通 `select ... status=="pending"`，**没有 `FOR UPDATE SKIP LOCKED`、没有 lease/claim token**。两个 Edge 或重试会同时执行同一任务 → 重复扫描/重复回执（仅靠批次 digest 兜底 at-least-once）。注册码领取反而是原子的（`:151` `with_for_update`），形成鲜明对照。

### 3.3 识别 Classify——关键词置信度，不是识别

- 确定性分类器（`app/classification.py:41-68`）只输入 `asset.name` + `owner_user_id`，**framework 字段根本没参与**；置信度 0.9/0.6/0.3 是启发式硬编码，`system_candidates`/`capability_hints` 永远为空。
- 模型辅助分类（`:87-132`）只喂 `{name}/{framework}`，不喂任何内容或行为；失败时返回 `None` + 错误引用（不静默降级，这点是对的）。
- **评测集基线诚实但量错了东西**（`docs/eval-baseline.md`）：6/8 召回 = 0.75、误报 0%，**量的是「名称是否命中智能体词表」，不是「这个东西是不是智能体」**。hard 组 0/2 的差距被写死锁住——这是诚实的，但也说明分类能力边界极窄。
- 对杀毒软件的类比：识别恶意程序不能只靠文件名，需要**程序内容特征（PE/ELF 头、导入表、行为特征）**。当前连内容都不读，识别无从谈起。

### 3.4 风险 Risk——治理状态规则，无风险量化模型

- 规则引擎 5 条规则（`app/rules.py:41-176`）：无 owner、心跳过期、证据过期、共享凭据、无 effective 权限——**全部是治理状态检查，没有一条看脚本内容、依赖、网络行为或持久化**。
- **没有风险评分模型**。产品承诺「识别风险高低」，但当前没有从「暴露面 × 行为 × 信誉 × 漏洞」合成风险分的机制；「风险高低」只能来自规则命中数。
- 对标：杀毒软件的「风险」= 检测引擎命中 + 信誉/行为加分 + 处置；本项目的「风险」= 有没有人认领 + 心跳是否过期。这是产品定位上的根本差异。

### 3.5 恶意脚本检测 Detect——完全缺失（产品承诺偏差最大的地方）

- 全仓库（Go + Python）无 YARA、无 IOC、无 AST/解释器语法分析、无行为分析、无信誉系统、无 detonation/沙箱执行、无 quarantine 状态（已全面 grep 验证）。
- Connector 协议里有「恶意配置不执行」的负向测试，但那是**「不当数据执行」的防护，不是检测**。
- 没有任何机制回答「这个脚本是恶意吗」。产品不能宣称具备杀毒式扫描。

### 3.6 权限管控 Control——局部闭环，静态策略不可部署

- **真实可闭环的只有动态网络策略**：`cli_backend.py` 的 `apply_dynamic`（266-293）→ `policy set` → revision 读回 → `effective`，v0.0.104 实弹通过。
- **文件系统/进程/静态网络策略（`needs_generation=True`）全部不可部署**：`cli_backend.py:295-299` 的 `create_generation()` **直接抛 `AdapterError`**（网关 SandboxResponse 解码缺陷未随 CLI 路径修复）。也就是说，UI 五域编辑器里最值钱的文件系统读写边界、进程限制，审批通过后部署**必然 502**。
- **`verify` 不是行为验证**：`cli_backend.py:301-328` 只做 revision 读回 + 网络允许集 membership 检查，拒绝检查用的是**合成的 `10.255.255.255:1`** 端点（`policies.py:404`），**没有一次真实的运行时 allow/deny 探测**。`stream_events`（350-355）把 `policy list` 的文本伪装成事件流。
- **P0 级越权缺陷（target 绑定）**：`policies.py:372` `deployment.target = body.target`——部署接口接受调用方**任意字符串 target**，`:397/:399/:405` 原样传给 adapter，**从未校验 target 是否对应 policy selector 里的 agent_ids**。后果：给 A 审批的策略可能被部署到 B；`inventory.py:925-929` 的 enforcement 状态只要「存在任一 effective 部署」就报 `enforced`，**不校验该部署的 target 是否就是本资产**。控制台可能把 A 显示为「已管控」，实际受控的是 B。
- **enforcement_mode 名存实亡**：模型层面 `audit_only/warn/block` 齐全（`contracts.py:81`），但 router 在 `policies.py:362-366` **硬拒非 block**（422），且 `read_effective_policy` 硬编码 `enforcement_mode="block"`（`cli_backend.py:243`）。渐进执行目前止于设计与审批状态机。

### 3.7 行为管控 Behavior——无事件源

- 没有从 agent 运行时采集行为事件的链路：进程执行、文件写入、网络连接、工具调用、模型调用——任何一类都没有结构化的行为事件。
- OpenShell 侧 `stream_events` 是假的；hermes 的 Runs API 是内存态 60s TTL（设计评审已证实）；也没有 auditd/eBPF 主机事件源。
- **没有行为证据 = 无法支撑「行为精准管控」**，也意味着「阻断」无法用行为证据证明生效（与 3.6 的 verify 缺口互为因果）。

### 3.8 审计治理 Audit/Govern——最完整的部分（可复用为差异化卖点）

- 审计与状态变化**同事务**写入（`test_confirm_writes_audit_and_outbox_same_transaction`），Outbox 事件同事务落库由 worker 发布。
- 敏感错误只存类型+哈希，Secret 明文永不落库/不进日志；响应错误只返回 error digest。
- SoD + break_glass 独立权限点 + 到期复核 + 幂等键 + 未批准不可部署（409）+ 漂移检测——**这是合规审计最爱的证据链**，商业价值可直接复用。

### 3.9 跨平台——「任意系统」是未被证明的表述

- Edge/Connector 是 Go 子进程，但 Connector 启动是**裸 `exec.CommandContext`**（`connector.go:146`），无进程组、无 namespace、无 seccomp、无 cgroup、无低权限用户；二进制解析走 `SIQ_CONNECTOR_BIN_DIR`/PATH（`:347-377`），**无 digest/签名校验**——PATH 被污染即可任意代码执行。
- `NetworkAccess=false` 只是**声明式 flag**（`protocol.go:81`），没有 seccomp/netns/防火墙兜底——恶意 Connector 可自由外联。
- 运行依赖 Linux 命令 + OpenShell 沙箱；无 Windows/macOS 传感器。产品说明书上应写支持矩阵，而非「任何系统」。

## 四、对 OpenShell 二次开发的专项评估

### 4.1 方向正确：Adapter 而非 Fork

- ADR-005/009 选的「版本化 adapter + 能力探测 + patch 治理、不长期 Fork」是对的。两个 OpenShell patch（landlock-mask / bind-mount-contract）经 D1 spike 验证已基本被上游 v0.0.104 吸收，升级成本 ≈0——**这个判断要保住**，别因为产品压力开 Fork 口子。

### 4.2 Adapter 契约逐项现状

| 契约方法 | 现状 | 判断 |
| --- | --- | --- |
| `probe` | 硬编码 `v0.0.83-policy-v1` + 固定 capability（`cli_backend.py:173-188`） | ⚠️ 与 v0.0.104 迁移状态漂移，能力未真正探测 |
| `compile` | 5 域路由（filesystem/process/network/model/credential），其余域显式 `unsupported`（`policy_compiler.py:20-26,88-94`） | ✅ 诚实标注，但**核心域（tools/secrets/data_scope/resources）全在 unsupported 列表** |
| `plan`/`apply` | 动态网络段热更新闭环 | ✅ 唯一真实闭环 |
| `create_generation` | **直接抛错**（`cli_backend.py:295-299`） | ❌ 文件/进程/静态策略不可部署 |
| `verify` | revision 读回 + membership，非真实行为 fixture | ❌ 见 3.6 |
| `observe` | `stream_events` 返回 `policy list` 文本伪装事件 | ❌ 无真实事件流 |
| `rollback` | `policy get --rev N-1` → `policy set` | ✅ 结构合理，仅网络段可回滚 |

### 4.3 关键结构性局限：OpenShell 管不到宿主机上的 agent

- OpenShell 是**沙箱策略网关**，只能对**进了它沙箱的 agent** 施加文件/进程/网络策略。而 hermes、piagent、workbudy 这类**直接跑在宿主上的 agent**，OpenShell 根本不在执行路径上——「精准管控」对它们目前是**零能力**。
- 这正是本评估确认**双轨并行**路线的原因：OpenShell 管沙箱内，Host Sensor（进程/文件/网络审计 + OS 级强制）管宿主机直跑 agent。OpenShell 的角色边界应定义为「**受管沙箱执行后端**」而非「全平台主机防护产品」。
- 隐含工程动作：把 OpenShell 的能力合同升级为**版本化 capability document**（sandbox 生命周期 / L3-L4 网络 / L7/DNS / MCP-tool / 模型路由 / 凭据注入 / 资源配额 / 行为事件 各自 `supported/unsupported/unknown` + `advisory/observe/enforce`），每项都要有真实验证路径，否则一律不得声称已管控。

### 4.4 Patch 治理与版本漂移

- `probe` 硬编码 v0.0.83 而 README/ADR 已推进到 v0.0.104（`docs/adr/0009` 标记 V1-V5 语义验证待完成）——版本字符串漂移是「能力未真探测」的症状，应改为：`probe` 只返回实测结果，capability 由真实 CLI 探测 + 语义 fixture 得出。
- 5 个本地 patch（OpenShell ×2 + Hermes ×3）建议按上游化节奏逐步退役，并纳入版本兼容矩阵 CI，而非靠人手维护。

## 五、优化方案（分优先级，全部含验收口径）

### P0——产品化前必须完成（安全承诺不破）

**P0-1 策略 target 与运行时目标的不可变绑定**（越权缺陷）

- 问题：`policies.py:372` 接受任意 `body.target`，未校验是否对应 selector 的 agent_ids；`inventory.py:925-929` 把「任一 effective 部署」当「已强制」。
- 建议：引入 `AgentIdentity → AgentInstance → RuntimeBinding` 三层身份；部署接口只接受 `agent_instance_id` 或服务端生成的 binding ID，target 由服务端解析；OpenShell snapshot/deployment/permission-fact/行为事件全部引用同一 instance/binding ID。
- 验收：负向测试——租户内 A 的策略不能部署到 B；跨租户 agent_id/environment/sandbox_id 拒绝；binding 撤销后不可再发布；enforcement 徽标必须校验 target==本资产才显示 enforced。

**P0-2 静态策略不得进入 effective**（安全错觉）

- 问题：`create_generation` 抛错但上层可能把 compiled/planned 当 effective；文件/进程策略部署必然 502。
- 建议：generation 路径修复前，**任何含静态字段的策略在部署前明确拒绝**（fail-closed 422）；实现 `create→validate→verify→cutover→observe→rollback` 生命周期；verify 用真实 allow/deny fixture（文件/进程/网络/失败关闭各一组），无行为证据只能标 `readback_verified`，不得标 `enforcement_verified`/`effective`。

**P0-3 拆双分析域：威胁检测平面 ≠ 治理平面**

- 问题：把「资产识别/治理状态」当「威胁检测」是承诺偏差。
- 建议：明确两条产品线——(a) **Analysis Plane**：采集哈希/类型/大小/权限/路径/来源/签名/依赖锁定 + 受控脱敏内容 → 静态规则/AST/YARA/信誉 → 隔离 detonation → Finding + quarantine；(b) **Policy Decision Plane**：现有治理闭环继续演进。两平面共享 Asset/Evidence，但结论语义分开。

**P0-4 最小恶意检测流水线（先回答「是否恶意」）**

- 建议：哈希+类型识别 → 静态规则（危险命令/下载执行/凭据读取/持久化/混淆/外联/提示注入载荷）→ YARA 签名 → 隔离 detonation（一次性、无凭据、无主机网络、快照回收）→ 结构化 Finding（规则 ID/证据哈希/命中位置/置信度/严重度/分析器版本/可复现摘要）。模型只辅助研判，不单独定 allow。
- 验收：恶意样本集按类别统计召回/误报（目标 ≥95% 召回，误报 1-5% 且人工复核）；确定性规则绝不误杀（沿用现有「零误报基线」纪律）。

**P0-5 Connector 可信执行与 OS 隔离**

- 问题：裸子进程 + PATH 解析 + 无网络隔离（`connector.go:146,347-377`；`protocol.go:81`）。
- 建议：Connector 二进制 digest allowlist + 签名校验；Linux 用独立低权限用户 + namespaces + seccomp + 只读根；进程组/进程树回收；Windows Job Object、macOS sandbox profile 对齐；`NetworkAccess=false` 必须有真实网络隔离兜底而非声明。

**P0-6 诚实产品表述 + 支持矩阵**

- 建议：README/售前口径改为「智能体资产发现、风险治理与受管沙箱策略控制平台」；发布明确支持矩阵（OS、框架、执行后端能力状态），删除「任意系统/所有智能体」表述，或在每个能力旁标注真实状态（supported/unsupported/unknown + verified 层级）。

**P0-7 修复已确认的工程缺陷**

- 任务领取原子化（`environments.py:201-223` 改 `FOR UPDATE SKIP LOCKED` + lease/claim token + receipt 去重）；
- 候选入账保留 `artifact_digest/attributes`（`inventory.py:350-358`）；
- 目录采集字节预算越界（`connectors/directory/directory.go:272,350-363`，剩余预算 0 时返回 truncated 而非读默认 1MiB）；
- 跨租户对象引用校验（confirm 时 `system_id`/`owner_user_id` 必须校验同租户 + 存在性）；
- `ruff` 2 处 B018 修掉并纳入 CI 阻断（`cli_backend.py:104`、`config.py:101`）。

### P1——形成可销售闭环

**P1-1 扩展发现源与框架覆盖（双轨的传感器侧起步）**

- 新增 Linux process/systemd、Windows service/process、macOS launchd/process、Kubernetes、MCP server 发现源；
- 为 **OpenClaw/Hermes 做 fixture 驱动 Connector**（已有），新增 **PiAgent/WorkBuddy/Dify 的 fixture 驱动 Connector**；未知框架进入 generic discovery 而不是静默漏报；
- docker Connector 去掉标签依赖，扫描全部候选容器再按元数据分类。
- 验收：受支持框架 fixture 发现召回率 ≥95%；未知框架必须进 generic candidate；漏报率持续可观测。

**P1-2 行为事件流 + 真实验证 fixture**

- 建立结构化行为事件（进程/文件/网络/工具/模型/凭据），来源：OpenShell Interceptor（待探测）+ 主机审计（auditd/eBPF）+ hermes/dify 等运行日志；
- 每个执行点提供 allow/deny/boundary/adapter-error 四类 fixture，验证结果含请求/预期/实际/事件 ID/策略 revision/时间窗。

**P1-3 补齐被标 unsupported 的核心管控域**

- secrets 注入、tool/MCP 策略、data_scope、模型路由、资源配额——不能只停在 `unsupported` 列表，至少给出一个可执行后端的闭环（哪怕先做 secrets 引用注入 + 配额）。

**P1-4 分级曝光与降级通道**

- enforcement_mode 的 `audit_only/warn` 真正落地（配合 OpenShell 支持或主机传感器），让客户先观察再阻断；漂移检测时延设定 SLO（如 ≤60s 检出）。

**P1-5 风险评分模型**

- 从「规则命中数」升级为可解释风险评分：`Risk = f(暴露面, 行为, 信誉, 漏洞, 治理)`，每项有证据链；Finding 自带分项分数与处置建议，支持人工覆写并留痕。

### P2——规模化与长期维护

1. OpenShell 版本兼容矩阵 + 上游升级 CI + 迁移 runbook + 自动回滚（V1-V5 语义验证落地）；
2. 独立部署回执 verifier / attestation，降低对 Edge 自报状态的信任（威胁模型 TODO）；
3. 规则/YARA/信誉/模型版本的签名更新机制，支持离线缓存与回滚；
4. OCSF（或等价）事件规范，SIEM/工单/取证导出；
5. 跨平台安装器、升级、卸载保护、Edge 防篡改、离线失联处置（双轨 Host Sensor 的完整产品化）。

## 六、目标架构（双轨并行）

```text
                    ┌────────────── Analysis Plane（威胁检测）──────────────┐
 Host Sensor        │  static rules / YARA / AST → detonation sandbox →     │
 (eBPF/auditd/OS)   │  Finding + Quarantine（证据哈希、置信度、处置建议）     │
        │           └──────────────────────────────┬───────────────────────┘
        │  discovery, process, fs,                 │  Threat Signals
        │  network, service, MCP                   ▼
        ▼                    ┌─── Policy Decision Plane（治理/管控）────────┐
 Canonical AgentIdentity →   │ risk scoring → approval(SoD) → compile →     │
 AgentInstance /              │  policy set → verify(fixtures) → effective  │
 RuntimeBinding               └──────────────┬──────────────────────────────┘
        │                                    ▼
        ▼                    Enforcement Plane（双轨）
  ├─ OpenShell sandbox（文件/进程/网络/凭据注入）      ← 已有闭环
  └─ Host OS Provider（进程/文件/网络/服务强制，       ← 新增
    覆盖宿主机直跑 hermes/piagent/workbudy）
        ↓
  Events, Receipts, Drift, Audit（同一证据链回链）
```

统一对象：`AgentIdentity`（框架/版本/来源/稳定指纹）、`AgentInstance`（安装/配置/主进程/容器）、`RuntimeBinding`（实例×执行后端的不可变绑定）、`Evidence`（哈希/来源/时间/截断/脱敏状态）、`Finding`（规则/严重度/置信度/证据引用）、`BehaviorEvent`（六类行为）、`PolicyDecision`（输入/策略版本/能力快照/结果/解释）、`QuarantineCase`（隔离/保全/密钥撤销/恢复审批/处置）。

产品模式三态：**Observe**（发现/分析/告警/审计，不声称已阻断）/ **Enforce**（仅当目标被可信 binding 管理且执行点经行为验证，才展示 enforced）/ **Unknown/Degraded**（失去心跳、能力探测失败、回执无效时降级，不自动放宽权限）。

## 七、验收指标建议（上线门槛）

- 受支持框架 fixture 发现召回率 ≥95%；未知框架必须进 generic candidate，漏报率持续可观测；
- 扫描新鲜度 <60s；重复任务率 <0.5%（任务原子领取后）；
- 恶意样本按下载执行/凭据窃取/持久化/外传/混淆/提示注入分类统计，召回 ≥95%，误报按类别 1-5% 且人工复核；
- target 绑定错误率**必须为 0**：跨 tenant/environment/instance 部署负向测试全部通过；
- 本地策略决策 p95 <100ms；撤销/阻断在定义窗口内生效（≤5s 心跳/事件窗口，明确离线行为）；
- 文件/进程/网络/MCP-tool 至少各有 allow/deny/异常/回滚四类行为测试；
- 无证据、能力未知、回执失效、版本不兼容时**不得进入 effective，不得自动放宽权限**；
- 审计事件完整率 100%；每次决策可追溯 tenant/instance/binding/策略 digest/能力快照/执行回执。

## 八、评估方法与限制

- **本人核实**：三处 P0 关键结论亲自读码确认（`cli_backend.py:295-299` create_generation 抛错、`inventory.py:881-932` enforcement 状态计算、`policies.py:355-414` deployment target 直传）；另三个维度（控制面/Edge+Connector/OpenShell 适配器+Web）由并行独立探索后交叉比对。
- **交叉一致**：结论与今日既有审计报告 `agent-security-audit-20260820-153735.md` 高度一致，无相反发现。
- **限制**：Go 工具链缺失，Edge/Connector 的编译、运行时与竞态验证未完成；未连接真实 OpenShell 多版本环境做动态验证；成熟度评级是基于源码与测试的产品判断，不是第三方认证或渗透测试结论。

## 结论

项目工程地基扎实、治理层优秀，方向和 OpenShell 接入方式正确；四项产品承诺中「恶意脚本检测」与「宿主机行为管控」是必须新建的能力，「任意系统/所有智能体」的表述需先收敛为诚实支持矩阵。建议按 P0（绑定身份、诚实管控状态、拆双平面、最小检测流水线、Connector 隔离）→ P1（发现源与行为事件、核心管控域闭环、风险评分）→ P2（版本矩阵、回执证明、签名更新、跨平台产品化）推进。
