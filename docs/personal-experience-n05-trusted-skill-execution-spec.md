# N05 可信 Skill 执行上下文：信任边界与同调用绑定规格 v1

生成：2026-09-14（kimi/personal-v4-r01-20260914，基于 main `b303c6f`）。来源：任务书 v4.0 §5（R01）。本规格取代旧树 held 的 `personal-experience-n05-skill-attribution-spec.md` 草稿；旧草稿未通过审查，本文不复制其内容。

本规格回答三个问题：谁能产生什么事实（§1）；当前真实平台在工具调用边界能提供什么（§2）；在此之上最小可执行的可信绑定是什么（§3–§6）。

## 1. 信任边界：事实来源清单

决策请求 `/v1/decide` 到达引擎时，各字段的产生者与可复制性如下。「模型可复制」指宿主内模型输出（含被 Skill 提示词诱导的输出）能否自行赋值该字段；「其他 Skill 可复制」指同宿主另一 Skill 的文本/工具行为能否造成同值。

| 事实 | 产生者 | 模型可复制 | 其他 Skill 可复制 | 处理规则 |
| --- | --- | --- | --- | --- |
| `tool`、`params` | 模型输出，宿主透传 | 是（本就是模型选择） | 是 | 永不作为归属依据；只作为被裁决对象 |
| `skill` claim（skill_id/version/content_hash） | 调用方自报 | 是 | 是 | 仅作提示；无服务端绑定恒 unknown，不产生 verified |
| 安装内容摘要、grantID、grant 元数据 | SIQ 状态，但值公开可读 | 是（同 UID 可读状态目录副本值） | 是 | 复制合法摘要/ID 不得提升归属等级（state.go 现行） |
| `session_id` / `tool_call_id` / `runtime_task_id` / `run_id` | 宿主运行时赋值，适配器转发；Hermes hook 的原生 `task_id` 映射为决策协议 `runtime_task_id` | 否（模型输出够不到钩子 kwargs） | 间接：同进程代码可伪造整个请求（见威胁范围） | 可作 SEC 主体与重试绑定的组成部分；不替代可信 Intent `task_id` |
| `task_id`（决策协议） | daemon 从已签名 Intent/session binding 解析；调用方只可给出一致性提示 | 否 | 否（错误提示被拒绝） | 仅表示可信 Intent 任务；不得承载 Hermes/OpenClaw 的宿主路由 ID |
| `agent_id`（managed） | 安装器写入适配器配置，宿主值被拒 | 否 | 同进程代码可伪造 | 主体绑定组成部分 |
| `Authorization: Bearer` / ri- 凭据 | daemon 发行，0600 凭据文件 | 否 | 同 UID 进程可读文件 | 认证用途；不构成 Skill 归属 |
| intent / authority 包络、binding、context assertion | daemon 签发（状态目录私钥） | 否 | 否（不可伪造签名；可复制 ID 引用但验证失败） | 现行信任根 |
| SEC（本规格 §3） | daemon 签发（状态目录私钥） | 否 | 否（同上；跨主体复制在验证期失败） | 本规格新增的信任根 |

威胁范围声明（验收时必须逐字保留）：本设计抵御的威胁是**模型可控输入与其他 Skill 的文本/调用层伪造**（复制 claim、摘要、grantID、session/task 标识、SEC ID）。它不抵御：已攻陷的宿主进程（可绕过钩子）、同 UID 恶意本地代码（可读 0600 凭据文件并冒充适配器发起整个请求）、OS 层沙箱逃逸。desktop-same-uid 边界见 dev-spec §6。

## 2. 平台能力核实（2026-09-14 实机，Linux aarch64）

核实方法：直接阅读本机已安装宿主的运行时源码/分发物中工具调用分发点。原始命令与输出见本批证据 `docs/evidence/personal-experience/r01-skill-execution-context-*/`。

### 2.1 OpenClaw 2026.5.12（~/.local/bin/openclaw，plugin-sdk 分发物）

`before_tool_call` 钩子事件载荷（dist/plugin-sdk/dispatch-*.js，`runBeforeToolCallHook`）：

- event：`{toolName, params, runId?, toolCallId?}`
- ctx：`{toolName, agentId?, sessionKey?, sessionId?, runId?, toolCallId?}`

**无 Skill 归属字段。** 分发物中的 `skillInvocation`/`skillName` 仅用于斜杠命令技能调用：用户输入 `/skill args` 被改写为提示文本「Use the "X" skill for this request.」，随后一切工具调用仍是模型选择。即：技能是提示词来源，不是运行时边界；OpenClaw 无法告诉适配器「这次 read_file 调用由 Skill X 引起」。

### 2.2 Hermes Agent v0.21.0（/home/maoyd/siq/hermes-agent，本机 venv 安装）

`pre_tool_call` 钩子分派（hermes_cli/plugins.py `_dispatch_pre_tool_call_hooks` → `invoke_lifecycle_hook`）传入 kwargs：`tool_name, args, task_id, session_id, tool_call_id, turn_id, api_request_id, middleware_trace`。

**无 Skill 归属字段。** 适配器签名中的 `parameter_provenance`/`context_assertion_id` 在当前安装版本的任何分派点均不被宿主赋值（全仓 grep 无生产传递点），恒为空。Hermes 的技能同样以提示词/skill_manage 工具形式存在，无逐调用因果归属。

### 2.3 结论

2026-09-17 macOS arm64 对已安装 OpenClaw 2026.9.4 的公开 `PluginHookBeforeToolCallEvent` 类型及原生包装器再次核实：工具事件新增 `toolKind`、`toolInputKind`、`derivedPaths` 等，但仍无模型不可伪造的「本次工具调用由哪个 Skill 造成」字段。`derivedPaths` 仅为非权威路径提示；`skillName` 仅在宿主自身 Skill Workshop/斜杠命令等内部路径出现，未作为每次工具调用的因果事实进入钩子。本批仍只可认定 SEC 的 `controlled_session` / `controlled_task`，不得提升为逐调用 Skill 因果归属。[OpenClaw 官方工具钩子合同](https://docs.openclaw.ai/plugins/hooks/tool-policy)与本机分发物均如此；其他宿主仍需各自原生证据。

当前两个已装宿主在工具调用边界**都不能**提供模型不可自行赋值的 Skill 归属。能力缺口成立；按任务书 §5.2.2 选择现有受控启动路径（managed 实例 + runtime identity + 签名 binding）上的最小可执行方案，即 §3 的 SEC。不得把「已安装钩子」表述为「可信宿主归属」。

## 3. Skill 执行上下文（SEC），合同 `skill-execution-context/v1`

SEC 是 daemon 签发的、有限期的、主体绑定的 Skill 执行上下文文档。它是归属从 unknown 提升到 verified 的**唯一**路径。

### 3.1 字段

| 字段 | 含义 |
| --- | --- |
| `schema_version` | 恒 `skill-execution-context/v1` |
| `context_id` | `sec-` 前缀随机 ID |
| `issuer_id` | 恒 `local-admin`（与 context-assertion 同一签发身份；签名私钥只在状态目录） |
| `subject` | `{platform, instance_id, agent_id, session_id, task_id?}`。task_id 仅在宿主提供（Hermes）时绑定 |
| `skill` | `{skill_id, version, content_hash}`：与安装记录、skill grant 完全一致的身份 |
| `install` | `{install_id, claim_signature}`：签发时重读的安装记录身份 |
| `authority` | `{grant_id, grant_digest}`：签发时对 grant  canonical 字节的 sha256；任何修订/撤销/状态翻转改变 digest |
| `evidence_level` | `controlled_task`（绑定 task_id）或 `controlled_session`（仅会话粒度） |
| `issued_at` / `expires_at` | RFC3339；TTL 上限 24h，且不得超过所绑定 runtime identity 的 session 有效期 |
| `signing_schema` / `signature` | `signing.SchemaLocalCanonicalV1`，daemon 私钥签 canonical 字节 |

### 3.2 签发前提（全部满足才签发，任一失败即拒绝）

1. 调用方持有管理面能力（capAdmin；决策 token 不可签发）。
2. `subject.platform + instance_id + agent_id` 存在未吊销的 runtime identity 签名记录；`session_id` 已完成该 identity 的 enroll（签名 session binding）。
3. `install` 重读：`skillinstall` Catalog 存在匹配 `install_id` 的记录，`recorded_status` 为已安装完成态，计划摘要与 `skill` 一致。
4. `authority` 重读：`grant_id` 存在、生命周期有效、`grant.Skill` 与 `skill` 完全一致；`grant_digest` 由 daemon 现场计算，调用方不得提供。live 判据与引擎的安装绑定语义一致：status 为 deployed/effective，或为 approved 且准入是 import 保留记录（安装流水线的真实终态，`importsource.Reserved`；此状态要求安装记录同时匹配，见第 3 条）。
5. 同一 subject 已存在未过期、未撤销的 SEC 时拒绝重复签发。会话级 SEC 与同会话所有任务级 SEC 互斥；任务级 SEC 只可与同会话的其他明确 task 并存，避免按随机 context ID 选中另一 Skill。续期须显式撤销旧上下文。
6. `expires_at` 取请求 TTL 与签名 session binding 剩余期限的较早者。离线 `skill-context` 管理命令必须取得状态单写者锁；daemon 运行时由管理面执行，CLI 不得绕过。

在线管理合同为 `local-skill-execution-context-issue/v1` 与 `local-skill-execution-context-revoke/v1`。`POST /v1/skill-contexts` 只接受实例、会话、可选宿主任务、安装 ID、TTL、操作人和显式确认；不得接受 skill、agent、platform、Grant 或摘要。`GET /v1/skill-contexts/{id}` 返回签名 SEC 原文。`POST /v1/skill-contexts/{id}/revoke` 必须携带刚读取的 `expected_context_signature`、操作人和显式确认，陈旧签名拒绝。三者仅允许 capAdmin，决策凭据不可访问。

签发和撤销在发布不可变签名文件前，先写入不含会话、任务、路径或参数原文的管理授权审计；审计失败时禁止发布。审计事件表达“管理员已授权该尝试”，最终是否生效仍以签名 SEC/撤销墓碑是否存在为准，因此发布中断不会制造虚假的有效授权结论。

SEC 落盘为状态目录 `skill-contexts/<context_id>.json`（排他发布，0600，只新建不改写）。撤销为独立签名墓碑 `skill-context-revocations/<context_id>.json`。**适配器、UI、SKILL.md 脚本永不持有签名私钥；SEC ID 不是秘密，其价值在绑定而非占有。**

### 3.3 验证（每次决策全量重验，不缓存信任）

引擎在 Decide 内对请求主体 `(platform, agent_id, session_id, runtime_task_id)` 做**服务端查找**（不是调用方引用 SEC ID）。旧客户端未提供 `runtime_task_id` 时才兼容回落到 `task_id`：

1. 取出该 subject 全部未撤销 SEC，逐一验签、验有效期、验 subject 完全相等（SEC 绑定 task_id 时请求 `runtime_task_id` 必须相等）。
2. 重读 runtime identity 与签名 session binding：实例、平台、agent、pin 的 Grant 均与 SEC 一致；绑定仍有效且有效期不短于 SEC。
3. 重读 `authority.grant_id`：存在性、deployed/effective、生命周期、现场重算 digest 与 `authority.grant_digest` 一致。
4. 重读 `install.install_id`：记录仍存在、状态仍为安装完成态、计划摘要仍一致；通过 session binding 的安装 Grant 校验再次核对目标内容（内容替换/移除/恢复中 → 失效）。
5. 全部通过且请求 skill claim 与 SEC skill 完全一致 → 归属 **verified**，回执记录 `context_id`、`evidence_level` 与本次调用的 binding 摘要（platform/session/agent/task/tool/tool_call_id/params 的 canonical sha256，即 trustedcontext.RequestBinding 同形）。
6. SEC 存在但任一校验失败 → 本次调用 **deny**（`skill_context_invalid`），不回落 baseline grant、不产生工具副作用。
7. 无 SEC → claim 走现行 unknown/mismatch 路径（state.SkillAttribution）。import 保留准入标识的已安装 Skill Grant 即使旧配置开关关闭也不服务；复制 claim、安装摘要或 grantID 只能得到 unknown + deny。

「参数在许可后改变」由执行点位置保证：适配器钩子在最终执行前调用，decide 请求携带的是最终参数；回执 binding 摘要覆盖最终参数。若宿主在钩子之后又改写参数（当前两宿主均无此路径的可见性），属 §2 能力缺口，UI 不得显示已覆盖。

### 3.4 权限交集（后端计算）

SEC 命中（verified）后，本次调用的有效权限 = **SEC 绑定 grant ∩ 该 agent 现行 baseline grant**（`Skill == nil` 的最新 deployed/effective grant；不存在时交集退化为 SEC grant 自身）。合成规则：

- 任一拒绝（工具/效果/host/path/scenario 不覆盖）→ deny；
- 任一要求审批且无拒绝 → hold；
- 两者均允许 → allow；
- 污点/trifecta 硬规则与 grant 无关，始终最后适用并可覆盖为 deny。

交集由引擎在后端现场算出；适配器与模型不参与。无 SEC 的普通 baseline Grant 行为不变；已安装 Skill 的保留准入 Grant 必须有 verified SEC。SEC 存在期间，**去掉 claim 不降级**：服务端按 subject 直接命中 SEC，仍按 skill 交集裁决——「去掉 claim 绕过限制」不成立。

### 3.5 失效条件（任一成立即 verified 不可得）

- SEC 过期或被显式撤销（墓碑存在）；
- grant 被撤销/修订/过期/状态翻转（digest 重算不等）；
- 安装记录被移除、进入 recovery_required 或计划摘要漂移；
- runtime identity 被撤销/替换、session binding 被撤销/过期/改 pin；
- subject 任一分量不符（跨实例/会话/任务复制自然失败）；
- 服务重启不改变上述规则（全部现场重读，无内存信任缓存）。

## 4. 证据等级与展示

- 回执 `skill_attribution` 扩展（receipt.v1 追加可选字段，不改动既有字段语义）：`status` 现行四值 + `evidence_level`（`controlled_task`/`controlled_session`，仅 verified 时存在）+ `context_id`（仅 verified 时存在）。
- 回执的 `task_id` 保留可信 Intent 任务语义，追加 `runtime_task_id` 记录宿主任务；两者都进入签名链。SEC `call_binding` 与原生审批重试只使用后者，错误的 Intent `task_id` 仍以 `intent_task_mismatch` 拒绝。
- UI 回执页只对 verified 显示「可信归属 · <证据等级>」及 context_id；unknown/mismatch 显示为未验证/不匹配；安装状态卡片不得显示「运行保护」。
- `controlled_session` 必须在 UI 明示粒度限制：「会话级：本会话全部调用归并到该 Skill，不含逐调用因果」。

## 5. 验收场景映射（任务书 §5.3）

| 场景 | 实现支点 | 测试 |
| --- | --- | --- |
| 真实受控调用 + 有效授权 | §3.3 全链通过，回执含 context_id/binding | 正向 engine+store+HTTP 集成；Hermes 实机批次 |
| 复制安装摘要/grantID/claim | §1 表 + §3.3.6 | 负向：无 SEC 时 claim 恒 unknown（现行测试保留） |
| 同 Agent 两 Skill 权限借用 | §3.4 交集 + subject 绑定 | 负向：窄 SEC 主体不命中宽 SEC；claim 切换不匹配 |
| 跨实例/会话/任务/调用复制 | §3.3.1 subject 完全相等 | 负向：改 session/task/instance 全 deny 且零副作用 |
| 参数改写/同名内容替换 | §3.3.2–3.3.4 | 负向：grant digest 漂移、install 状态漂移 → deny |
| Grant 撤销/修订、安装移除、重启 | §3.5 | 负向+恢复：撤销后立即 deny；重启后仍 deny |
| 缺来源/平台不支持 | §2.3 + §3.3.6 | unknown/unavailable，不默认可信（现行测试保留） |

## 6. 明确不做

- 不防御已攻陷宿主、同 UID 恶意进程、OS 沙箱边界（§1 威胁范围）。
- 不声称 OpenClaw 具备逐调用归属（仅 controlled_session 粒度）。
- 不把 SEC 用于扩大任何资源范围；SEC 不是 grant、不是 intent、不是审批。
- 不恢复旧树 `skill_attribution.go`/`action_state.go` 的任何断言路径。
- WorkBuddy 无上游运行时（本机未安装）：相关归属能力记 blocked，不以目录探测代替。
