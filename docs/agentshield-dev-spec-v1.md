# AgentShield 开发规格 v1（Development Specification）

- 日期：2026-09-04
- 状态：**生效**；实现必须以本文为准，偏离先改本文再改代码
- 上游文档：ADR-011（决策）→ `agentshield-design-v1.md`（方案）→ **本文（规格）** → `packages/contracts/`（合同事实源）
- 相关：`research/agentshield-market-survey-2026-09.md`、`detection-baseline.md`、`compatibility.md`、ADR-003/004/005

> 文档分工：设计方案回答「做什么、为什么」；本文回答「怎么做、边界在哪、怎么验证」。合同细节以 schema 为准，本文只解释语义与算法，不复制字段表。

---

## 0. 阅读顺序与术语

| 术语 | 定义 |
| --- | --- |
| Skill | 符合 agentskills.io 规范的目录：`SKILL.md`（YAML frontmatter + Markdown）+ 可选 `scripts/` `references/` `assets/` `evals/` |
| 平台 | 承载 Agent 的运行时：OpenClaw / Hermes / CodeBuddy（WorkBuddy）/ Trae（TraeWork）/ Claude Code / Codex |
| 适配器 | 把平台钩子接到本地二进制决策 API 的薄层 |
| 档位 | L0 审计 / L1 安装门禁 / L2 运行时回执与阻断 / L3 OpenShell 策略下发 |
| 五态 | permission-fact `state`：declared / inferred / observed / effective / unknown（ADR-004） |
| 本地模式 | 单机单用户、文件态、无关系库（ADR-011 D3） |
| 规则包 | `threat_rules.v1.json`：签名的正则检测 + 脱敏规则（Python/Go 共用） |

---

## 1. 架构与信任链

### 1.1 组件

```
SKILL.md ──(1) 校验 manifest 与二进制哈希──► agentshield 二进制
                                              ├─ inventory   ─► candidate / evidence
                                              ├─ admit       ─► admission + skill-card
                                              ├─ grant       ─► grant + desired-policy 引用
                                              ├─ serve       ─► /v1/decide ─► receipt 链
                                              ├─ openshell   ─► policy set / get --full
                                              └─ ui          ─► 127.0.0.1:<port>/
平台钩子 ──(2) 适配器 HTTP + 本地 token──────► /v1/decide
```

### 1.2 信任链（谁信谁、凭什么）

| 环节 | 信任根 | 校验方式 | 失败行为 |
| --- | --- | --- | --- |
| SKILL.md → 二进制 | `skill-manifest.json`（发布密钥签名） | bootstrap 脚本比对下载文件 sha256 与 manifest；manifest 签名由脚本内置公钥验证 | 拒绝启动，提示手动核对 |
| 二进制 → 规则包 | 内嵌包为基线；外部包需 `AGENTSHIELD_RULEPACK_PUBKEY` 验签 | Ed25519 over canonical JSON；版本 ≥ 内嵌 | 回退内嵌包，stderr 记类别 |
| 适配器 → 决策 API | 状态目录内 `token`（0600） | `Authorization: Bearer <token>`；只监听 127.0.0.1 | 401；适配器按 fail-closed 表处理 |
| 回执 → 阅读者 | 本地 Ed25519 身份（`keys/signing.seed`） | `agentshield verify` 重算哈希链并验签 | 报告首个断链/坏签位置 |
| 模型 → 任何裁决 | **无** | 模型只能触发子命令并呈现输出 | — |

### 1.3 不变量（实现红线）

1. 任何 `effective` 事实只能由后端读回产生（grant 读回 / receipt 观测不算 effective，记 observed）。
2. 任何签名密钥不离开状态目录；适配器、UI、SKILL.md 脚本都不持有私钥。
3. 回执、准入、签发文件只追加或只新建，从不原地改写。
4. 参数、文件内容、密钥原文不进入任何持久化字段；只允许 sha256 摘要与经脱敏、≤ 上限的 excerpt。
5. 外部输入（Skill 内容、钩子参数）永不被执行、导入或 `eval`；分析纯静态。
6. `enforcement_mode=block` 下决策 API 不可达或超时 = 拒绝（fail-closed）；`audit_only`/`warn` 下 = 放行并记 `advisory_action`。
7. 模型/LLM 输出（若未来接入语义层）只能产生 `inferred` 事实或 `info` 类 finding，不能改 verdict、不能改 action。

---

## 2. 本地模式：状态目录

### 2.1 路径

| OS | 默认 | 覆盖 |
| --- | --- | --- |
| Linux | `$XDG_STATE_HOME/agentshield`，否则 `~/.local/state/agentshield` | `AGENTSHIELD_STATE_DIR` |
| macOS | `~/Library/Application Support/agentshield` | 同上 |
| Windows | `%LOCALAPPDATA%\agentshield` | 同上 |

### 2.2 布局

```
<state>/
  keys/signing.seed        base64 32B，0600，O_EXCL 一次生成
  token                    决策 API bearer token，0600，首次 serve 生成
  config.json              enforcement_mode、port、平台适配器登记、OpenShell 端点
  inventory/<ts>.json      每次盘点一份：candidates[] + evidence[]
  admissions/<admission_id>.json
  admissions/<admission_id>.skill-card.md
  grants/<grant_id>.json   状态变更 = 新建 <grant_id>.<seq>.json，不改写
  policies/<policy_id>.v<version>.json
  receipts/<chain_id>/<YYYY-MM-DD>.jsonl   只追加
  receipts/<chain_id>/HEAD                 最后一条 hash + seq（崩溃恢复用）
  evidence/<evidence_id>.json
  logs/agentshield.log     类别级日志，无内容
```

目录 0700，文件 0600（Windows 不检查 POSIX 位，依赖用户目录 ACL）。

### 2.3 并发

- 单写者：`serve` 持有 `<state>/serve.lock`（O_EXCL 创建，内含 pid；启动时若 pid 不存活则接管）。
- 子命令（`admit`/`grant`）与 `serve` 同时运行时，通过 HTTP 提交给 `serve` 写入；`serve` 未运行则子命令直接写文件。
- 回执链：`serve` 内存持有 `(seq, hash)`；写入顺序 = 先 append 行、`fsync`、再更新 `HEAD`。恢复时以文件最后一行为准，`HEAD` 只是加速。

### 2.4 与控制面同步（可选，非现场）

`agentshield sync --control-api <url>`：把 `inventory/`、`admissions/`、`receipts/` 以现有 Edge 协议追加上传；本地是事实源，上传失败不影响本地决策。

---

## 3. 模块规格

### 3.1 `internal/canon`（已实现）

- `Marshal(v) []byte`：与 CPython `json.dumps(obj, sort_keys=True, separators=(",",":"))` 逐字节一致。
- 覆盖：键按码点排序、`ensure_ascii` 转义（含代理对、DEL）、float `repr` 规则、任意精度整数、拒绝 NaN/Inf。
- 测试：固定向量来自 CPython 实际输出。

### 3.2 `internal/rulepack`（已实现）

- 内嵌 `data/threat_rules.v1.json`；测试锁定与 `apps/control-api/app/data/threat_rules.v1.json` 逐字节一致。
- `Load(pub, warn)`：外部包路径 `SIQ_AS_THREAT_RULEPACK_PATH`；解析 → 验签（`<file>.sig` base64 Ed25519 over canonical）→ 版本 ≥ 内嵌；任一失败回退内嵌并 `warn(类别)`。
- 正则方言：RE2。规则包变更规则：**新增/修改模式必须在 CPython 与 Go 两侧编译并通过语料测试**（见 §8.2）。

### 3.3 `internal/threat`（已实现，含缺口）

- `Analyze(content, filename, contentType) Result`：sha256、类型识别、每规则首行命中、脱敏、40 字符截断、`excerpt_sha256`（脱敏前）。
- 与 Python 对等：共用 `corpus.json`；同一输入两侧 `sha256 / rule_id / line / excerpt_sha256 / excerpt` 相同。
- 缺口：Python AST 层 4 条规则未实现（`detection-baseline.md` 已记）。路线图：tree-sitter-python（cgo）或纯 Go 词法层；实现前 Go 侧对 Python 文件的置信度以正则规则为准。

### 3.4 `internal/signing`（已实现）

- `Load(stateDir)`：`AGENTSHIELD_SIGNING_KEY_SEED` 优先；否则 `keys/signing.seed`，O_EXCL 原子生成；损坏 seed 报错不重生成。
- `SignCanonical(doc)` / `VerifyCanonical(pub, doc, hex)`：128 hex，对 `canon.Marshal(doc 去掉 signature 字段)`。
- `SignBytes` / `VerifyBytes`：回执链对 `hash` 字符串字节签名。
- 与 Python 对等：同 seed 同文档签名十六进制相同（固定向量）。

### 3.5 `internal/inventory`（规格）

**输入**：平台列表（自动探测 + `config.json` 登记）。**只读**，不启动任何 MCP server、不导入任何脚本。

| 平台 | 读取 | 产出 |
| --- | --- | --- |
| Hermes | `~/.hermes/config.yaml`、`profiles/*/`、`skills/**/SKILL.md`、`platform_toolset_modes` | candidate（agent）、candidate（skill）、declared 事实（toolsets allowlist → tool 域）|
| OpenClaw | `~/.openclaw/openclaw.json` agents.list、`~/.openclaw/skills`、`~/.agents/skills`、`workspace/skills`、`security.installPolicy` 是否指向本机二进制 | 同上 + observed 事实（installPolicy 已接管 = L1 就位）|
| CodeBuddy | `~/.codebuddy/settings.json` hooks、`.codebuddy/skills` | candidate（skill）、observed（PreToolUse 已接管 = L2 就位）|
| Trae | `~/.trae/skills`、`.trae/skills`、`.agents/skills` | candidate（skill）；档位标 audit_only |
| MCP 配置 | 复用 `connectors/mcp`：只留 `env_keys`、`scheme://host`；不连接 | candidate（mcp_server）|

**输出**：`inventory/<ts>.json`，内容符合 `candidate.schema.json` + `evidence.schema.json`；每条 candidate 至少引用 1 条 evidence；`.env`/`auth-profiles`/`apiKey` 类字段只出 `secret_ref` 或 `size`。

**新增（相对现有 Connector）**：Skill 目录扫描——每个 `SKILL.md` 产出 candidate `source_type=skill_dir`（需在 `candidate.schema.json` enum 增加 `skill_dir`，合同升版），附 `content_hash` 与是否已有 admission 记录。

**实现方式**：Go 直接调用 `connectors/*` 包（`go.work` 引入），不经子进程 NDJSON；协议类型仍来自 `edge/agent/protocol`。

### 3.6 `internal/admission`（规格，W1 余量）

#### 3.6.1 输入与限额

- 输入：本地目录 / zip / git URL（git 只 `clone --depth 1` 到临时目录，不执行 hooks：`GIT_CONFIG_*` 禁用 `core.hooksPath`，并在完成后删除）。
- 限额（超限 → `integrity.over_limit=true` → quarantine）：

| 项 | 上限 |
| --- | --- |
| 文件数 | 2000 |
| 总字节 | 64 MiB |
| 单文件 | 8 MiB（超过只记哈希不扫描，计 `binary_files`）|
| 目录深度 | 16 |
| zip 嵌套 | 不解压嵌套压缩包，按 binary 计 |
| finding 数 | 500（达到即停止扫描并 over_limit）|

#### 3.6.2 遍历与哈希

- 遍历用 `filepath.WalkDir`，**不跟随符号链接**；对每个 symlink `EvalSymlinks` 后若不在 Skill 根内 → `symlink_escape=true`（quarantine），在根内则按普通文件计入。
- `file_manifest`：相对 POSIX 路径（`/` 分隔）、sha256、bytes；排除 `.git/`、`skill.oms.sig`、`skill-manifest.json`。
- `content_hash = sha256( join( sorted( "<path>\n<sha256>\n<bytes>\n" ) ) )`，与 `skill-manifest.skill.content_hash` 同算法。

#### 3.6.3 frontmatter 解析

- `SKILL.md` 必须以 `---\n` 开头、以 `\n---\n` 结束 frontmatter；否则 `frontmatter_valid=false`，finding `adm-frontmatter-invalid`（category integrity, disposition quarantine 仅当 `SKILL.md` 缺失；格式错误为 info）。
- 只解析扁平 `key: value`、`key: [a, b]`、块列表 `- x`、以及 `metadata:` 下一层缩进映射；不实现完整 YAML（无锚点、无多文档）。不可解析的键记 info。
- 识别字段：`name`（校验 agentskills 规则）、`description`、`version`、`license`、`compatibility`、`allowed-tools`（空格分隔或列表）、`platforms`、`metadata.hermes.*`、CodeBuddy 扩展 `context`/`hooks`/`agent`/`model`。
- **`hooks` 字段存在** → finding `adm-frontmatter-hooks`，category `capability_declaration`，disposition `declare`，产出 `process.exec` declared 事实（source_field `frontmatter.hooks`）。这是声明而不是隔离，但 Skill Card 必须高亮。

#### 3.6.4 检查项与处置映射

Finding 的 `disposition` 由**类别**决定，不由 severity 决定。规则包 `rule_id` → category 的映射固定在代码表 `admission/dispositions.go`，变更需同步本文：

| 来源 | rule_id / 检查 | category | disposition | 备注 |
| --- | --- | --- | --- | --- |
| 规则包 | `threat-prompt-injection` | prompt_injection | **quarantine** | 仅当命中位于 `SKILL.md` 正文或 `scripts/`；位于 `references/`、`evals/` 降为 info（NVIDIA 官方 Skill 误报来源）|
| 规则包 | `threat-net-webhook-exfil`、`threat-net-reverse-shell`、`threat-net-hardcoded-c2` | credential_exfil | **quarantine**（c2 因 0.8 置信 → declare）| 与控制面自动隔离阈值一致（≥0.85 才硬处置）|
| 规则包 | `threat-cred-*`（ssh/dotenv/system-files/cloud/browser-store/hardcoded-secret） | credential_exfil | **同文件同时存在出网槽** → quarantine；否则 → declare（`credential` 域 declared 事实）| 「读凭据 + 出网」才是外传；单独读 `.env` 是能力声明 |
| 规则包 | `threat-download-exec-*`、`threat-obf-*`、`threat-py-*` | dangerous_code | declare（`process.exec` / `package.install`）| 官方 Skill 常见 `curl \| sh` 安装步骤 |
| 规则包 | `threat-persist-*` | persistence | declare（`filesystem.write` 系统路径）| 若目标为 `~/.ssh/authorized_keys`、shell rc → quarantine |
| 内置 | `adm-hidden-html-comment`：SKILL.md 中 HTML 注释含指令动词（ignore/override/always/never/do not tell）| hidden_instruction | **quarantine** | 空注释或纯 TODO 为 info |
| 内置 | `adm-unicode-invisible`：零宽字符 U+200B–200F、U+2060–2064、U+FEFF（非 BOM 位置）、BiDi 控制 U+202A–202E / U+2066–2069 | hidden_instruction | **quarantine** | 仅检查 `SKILL.md` 与 `scripts/` 文本 |
| 内置 | `adm-unicode-homoglyph`：标识符/命令名混用拉丁与西里尔/希腊字母 | user_deception | **quarantine** | 只在代码文件与 frontmatter |
| 内置 | `adm-user-deception`：`SKILL.md` 正文出现「不要告诉用户 / do not (tell\|inform\|mention).*user / hide .* from the user」且不在引号示例或 `references/` | user_deception | **quarantine** | 引号内示例记 info |
| 内置 | `adm-allowed-tools` | capability_declaration | declare（每个工具一条 `tool.invoke`）| 不是越权 |
| 内置 | `adm-egress-domain`：脚本中的 URL 主机 | capability_declaration | declare（`network` `http.request` endpoint）| 去重；localhost/127.0.0.1 记 info |
| 内置 | `adm-package-install`：pip/npm/brew/apt/cargo/go install | capability_declaration | declare（`resource` `package.install`）| |
| 内置 | `adm-writes-outside-skill`：脚本写入 `~`、`/etc`、`$HOME`、`%APPDATA%` 等 | capability_declaration | declare（`filesystem.write`）| |
| 内置 | `adm-binary-file`：非文本文件 | supply_chain | info（计入 `binary_files`）；可执行位或 `.exe/.so/.dll` → declare `process.exec` | |
| 内置 | `adm-symlink-escape` / `adm-over-limit` / `adm-skill-md-missing` | integrity | **quarantine** | schema 已用 if/then 强制 |
| 内置 | `adm-name-mismatch`：frontmatter `name` 与目录名不一致 | info | info | |

**类别 → verdict**：

```
if any(disposition == quarantine) or integrity.over_limit or integrity.symlink_escape:
    verdict = quarantine
elif any(disposition == declare):
    verdict = admit_with_conditions; declared_facts = 去重(所有 declare 产生的事实)
else:
    verdict = admit
```

`source.trust_level` 影响：`trusted` 来源对 `dangerous_code`/`persistence` 的 declare 事实仍产出，但 Skill Card 标「官方来源」；不改变 quarantine 集合。

#### 3.6.5 evidence

每条 finding 与每条 declared 事实引用 ≥1 evidence：`evidence_id = ev-<sha256(path + line + rule_id)[:16]>`，`source_type=manifest`，`content_hash` = 命中行脱敏前 sha256，`classification=internal`，`signature` 由本地 key 签。evidence 写 `evidence/`。

#### 3.6.6 输出

- `admissions/<admission_id>.json`（符合 `admission.schema.json`，`signature` 覆盖去签名后的规范化文档）。
- `admissions/<admission_id>.skill-card.md`：NVIDIA 最小卡结构（Description / Owner / License / Use Case / Requirements / Known Risks and Mitigations / References / Output / Version / Ethical）。Owner、License、Use Case 取 frontmatter，缺失写 `[unknown]`；Known Risks 由 declared 事实与 finding 生成可执行陈述（「该 Skill 会向 api.github.com:443 发起 HTTPS 请求；grant 未放行前被拒」）。页脚固定：**「本卡由 agentshield 生成，不构成签名、批准或发布。」**
- stdout：JSON（默认）或 `--format sarif`（W5 可选）。退出码：admit 0、admit_with_conditions 0、quarantine 3、内部错误 1。

#### 3.6.7 变更重审

`admit` 时若 `admissions/` 已存在同 `skill_name` 且 `content_hash` 不同 → 输出字段 `supersedes=<旧 admission_id>` 并在 Skill Card 写「内容自上次准入已变更」；旧 grant 自动进入 `revoked`（写新 grant 版本文件）。

### 3.7 `internal/grant`（规格，W1 余量）

#### 3.7.1 输入

`admission.json` + `platform` + `subject` + 操作者（控制台或 CLI `--approve-as <actor_id>`；CLI 批准也算 human，但记录 `channel=hermes_cli` 等）。

#### 3.7.2 事实转换

| 输入 declared 事实 | 平台输出 | DesiredPolicy 域 |
| --- | --- | --- |
| `tool.invoke <name>` | Hermes：加入 `hermes_toolset_allowlist`；OpenClaw：`openclaw_tool_policy.allow` | `tools[]`（编译时按能力表落 unsupported：OpenShell `tools_mcp` 为 unsupported）|
| `network http.request <host:port>` | Hermes：无（靠 OpenShell）；OpenClaw：`exec`/`web_fetch` 保留在 allow 但由 `/v1/decide` 按域名判 | `network[] {endpoint, effect: allow, methods?}` |
| `filesystem write/read <path>` | — | `filesystem.read_only/read_write`；标 `static_domains_unavailable=[filesystem]` |
| `process.exec` | Hermes：`terminal` 进 allowlist；OpenClaw：`exec` 进 `require_approval`（默认）| `process.forbid_privilege_escalation=true`；标 static |
| `model.generate <model>` | — | `model_routing.allowed_models` |
| `credential <ref>` | 一律 **不**转为 allow；写 `deny` 事实 + `require_approval` | `secrets[]` 只允许 ref |
| `package.install` | OpenClaw：`require_approval`；Hermes：`terminal` 已含 | — |

规则：
- 未在 declared 中出现的工具/域名/路径不写入任何 allow（`default_effect=deny`）。
- `deny` 事实优先：同域同资源模式若同时有 allow 与 deny → `overlap_conflicts` 记 `deny_overrides`，输出只保留 deny。
- 同域资源模式重叠（glob 包含、前缀包含）且效果相同 → 记 `resolution=manual`，需人在控制台确认合并；未确认 = `unresolved`，schema 阻止 approved。
- 所有输出事实 `state=declared`（来自 admission）或 `inferred`（grant 推导，如 `process.forbid_privilege_escalation`）；**没有 effective**。

#### 3.7.3 状态机

```
draft ─► pending_approval ─► approved ─► deployed ─► effective
                │
                └─► rejected           any ─► revoked（admission 变更 / 人工）
```

- `approved` 需 `approved_by.actor_type=human`（CLI/控制台/OpenClaw approval 都是人；自动化脚本不得调用 approve）。
- `deployed`：Hermes 写 `platform_toolset_modes` allowlist 文件 / OpenClaw 写插件策略文件 / OpenShell `policy set`。写入前备份原文件到 `<state>/backups/`。
- `effective`：读回校验——Hermes 读回配置文件哈希；OpenClaw 读回插件策略哈希；OpenShell `policy get --full` 比对 revision + 网络段。读回成功才把对应事实改为 `effective` 并填 `authority_revision`、`readback_evidence_id`。fs/process 段永远不进 effective（`static_domains_unavailable`）。

#### 3.7.4 DesiredPolicy 编译

移植 `policy_compiler.compile_policy` 语义：能力表驱动（`BackendCapabilities`）、unknown 视为 unsupported、fs/process → `needs_generation=true`、网络 → 若 `dynamic_network_update=false` 也 `needs_generation`。Go 实现与 Python 对同一 DesiredPolicy 输出的 `artifact_hash` 必须一致（对等测试）。

### 3.8 `internal/receipt` 与决策 API（规格，W1 余量）

#### 3.8.1 HTTP

- 监听 `127.0.0.1:<port>`（默认 47611，`config.json` 可改）；拒绝非 loopback 远端地址。
- 认证：`Authorization: Bearer <token>`；token 文件仅 0600，适配器安装时读取一次。
- 端点：

| 方法 路径 | 用途 |
| --- | --- |
| `POST /v1/decide` | 工具调用决策（同步）|
| `POST /v1/observe` | 工具结果观测（after/post 钩子；用于污点更新，不做决策）|
| `POST /v1/hold/{receipt_id}` | 人工签核结果（body: `{"approve": bool, "actor_id": ...}`）|
| `GET /v1/receipts?chain=&since_seq=` | 分页读回执 |
| `GET /v1/status` | 版本、enforcement_mode、平台档位、链头 |
| `POST /v1/admit` / `POST /v1/grant/...` | 控制台与 CLI 复用；同 §3.6/§3.7 |
| `GET /` | 内嵌 UI |

请求体（decide）：

```json
{"platform":"openclaw","session_id":"...","agent_id":"...","tool":"exec",
 "tool_call_id":"...","params":{...},"context":{"cwd":"...","host":"sandbox"}}
```

响应：

```json
{"action":"allow|deny|hold|redact","reason":"...","receipt_id":"rcp-...",
 "params":{...仅 redact 时返回改写后参数...},
 "hold":{"channel":"openclaw_approval","timeout_ms":60000}}
```

预算：p95 < 200 ms；硬超时 2 s 内必须返回（超过由适配器按 fail-closed 表处理）。

#### 3.8.2 决策算法

```
1. 找 session 状态（内存 + receipts 回放）：taint_labels、trifecta 三布尔
2. 定位 grant：platform + agent_id → 最新 status ∈ {deployed, effective} 的 grant；无 grant → 按 default_effect=deny（block 模式）
3. 工具级：tool ∉ allow 且 ∉ require_approval → deny("tool not granted")
           tool ∈ require_approval → hold
4. 参数级：
   a. 参数序列化后过规则包 + 脱敏规则 → 命中 secret/pii 模式 → 打 taint；命中 threat 规则记 matched_rule_ids
   b. 出网类工具（exec 含 curl/wget/nc、web_fetch、http、send_message、browser）解析目标 host → 不在 grant network allow → deny
   c. 文件类工具解析路径 → 不在 fs allow 且非 cwd 内 → deny；命中 credential 路径（~/.ssh、.env、~/.aws）→ 打 private_mount taint
5. 污点规则：
   - 会话已有 secret/pii taint 且本次为出网类 → deny（"tainted egress"）
   - trifecta: private_data && untrusted_input && 本次出网 → deny；untrusted_input 由「已加载 admission 非 admit 的 Skill」或「web_fetch 结果观测」置 true
6. redact：仅当 grant 配置 `redact_secrets=true` 且命中的是参数中的密钥字面量 → 用脱敏规则替换后 allow，action=redact
7. enforcement_mode：audit_only → action=allow, advisory_action=原判定；warn → 同 audit_only 但 reason 前缀 WARN；block → 原判定
8. 写回执（§3.8.3），返回
```

`/v1/observe`：对工具结果做同样的 taint 扫描（结果里出现密钥 → secret taint；web 内容 → untrusted_input=true），不产生 action，写 `action=allow` 的观测回执并标 `matched_rule_ids`。

#### 3.8.3 哈希链

- `chain_id`：本地模式固定 `local`；同步到控制面后由控制面归属。
- 每条：`seq = prev.seq+1`；`prev_hash = prev.hash`（创世 64 个 0）；`hash = sha256(canon(receipt 去掉 hash/sig))`；`sig = Ed25519(hash 的 hex 字符串字节)`。
- `agentshield verify [--chain local]`：逐行重算，报告首个 `seq` 不连续 / `prev_hash` 不匹配 / `hash` 不符 / `sig` 无效。

#### 3.8.4 fail-closed 表（适配器侧行为）

| 场景 | block | warn / audit_only |
| --- | --- | --- |
| API 不可达 / 超时 / 5xx | deny（reason 写「decision service unavailable」，适配器本地写一条未签名的 `pending` 记录，恢复后由 serve 补签 `observed`）| allow + stderr 警告 |
| 401 | deny | allow + 警告 |
| 返回非法 JSON | deny | allow |

### 3.9 `internal/openshell`（规格）

- 后端只用 CLI（与 `cli_backend.py` 相同环境变量：`SIQ_AS_OPENSHELL_CLI_BIN`、`SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT` 或 `SIQ_AS_OPENSHELL_ENV_SH`）。
- `probe()`：`gateway info` + `policy get` 探测 `dynamic_network_update`、`revision_support`、`sandbox_list_decodable`；不按版本号假设。
- `apply(network)`：`policy set` 只提交网络段；`policy get --full` 读回 → 比对 → 产出 `effective_readback{backend:"openshell", revision}` 与 evidence。
- 不调用 `create_generation`；fs/process 段写入 `sandbox create` 时的策略文件（静态），并在 grant 里标 `static_domains_unavailable`。
- macOS/Windows：`probe()` 失败（无 Docker/WSL2）→ L3 不可用，UI 显示原因。

### 3.10 `internal/ui`（规格）

- 复用 `apps/web` 构建产物（`vite build` → `dist/`），Go `embed` 进二进制；构建脚本 `make ui` 先跑 `npm ci && npm run build`。
- 页面：Overview（档位、链头、平台登记）、Inventory、Admissions（列表 + 卡）、Grants（审批、重叠确认）、Receipts（链、红色 deny 高亮、验签按钮）、Settings（enforcement_mode、平台适配器安装/卸载）。
- 顶栏常驻标签：**「本地模式 · 单用户」** + 当前平台档位（如 `OpenClaw · L3` / `Trae · 审计模式，无法阻断`）。
- 所有写操作走 §3.8.1 端点并带 token；UI 无私钥。

---

## 4. 平台适配器规格

### 4.1 OpenClaw（P0）

**安装门禁（L1）**：`~/.openclaw/openclaw.json`

```json5
security: { installPolicy: { enabled: true, targets: ["skill","plugin"],
  exec: { source: "exec", command: "<abs path>/agentshield", args: ["policy-exec","--json"],
          timeoutMs: 10000, trustedDirs: ["<dir>"] } } }
```

`agentshield policy-exec`：stdin 读 OpenClaw 请求（含 staged 路径与 `skill.installSpec`）→ 对 staged 目录跑 §3.6 → 输出 `{"decision":"allow|warn|block","reason":...}`：quarantine → block；admit_with_conditions → warn（附「安装后请 grant」）；admit → allow。任何内部错误 → block（OpenClaw 自身在 exec 失败时也 fail-closed）。

**运行时（L2）**：插件 `adapters/runtime/openclaw-agentshield/`（TypeScript，`definePluginEntry`）：

- `before_tool_call`（priority 10）：POST `/v1/decide`；映射 `deny → {block:true, blockReason}`、`hold → {requireApproval:{title, description, severity:"warning", timeoutMs}}`、`redact → {params}`、`allow → undefined`。
- `after_tool_call`：POST `/v1/observe`（结果截断 64 KiB 后发送，服务端再脱敏）。
- 超时：插件侧 5 s；OpenClaw 钩子 15 s fail-closed 兜底。
- 配置：`~/.openclaw/agentshield.json` 保存 `endpoint`、`token_path`、`enforcement_mode`。

**卸载**：`agentshield adapter uninstall openclaw` 删除插件目录并把 `openclaw.json` 恢复到 `<state>/backups/` 中的副本。

### 4.2 Hermes（P0）

**运行时（L2）**：`~/.hermes/plugins/agentshield/`（`plugin.yaml` + `__init__.py`，纯 stdlib `urllib`）：

- `register(ctx)`：`ctx.register_hook("pre_tool_call", cb)`、`ctx.register_hook("post_tool_call", cb)`。
- `pre_tool_call(tool_name, args, task_id, session_id, tool_call_id)` → POST `/v1/decide` → `deny/hold` 返回 `{"action":"block","message": reason}`（Hermes 无 approval 通道：hold 在 Hermes 上退化为 block 并在 message 里给控制台 URL）；`allow` 返回 `None`。
- `post_tool_call` → `/v1/observe`。
- 插件不修改 Hermes 核心（AGENTS.md 规则）。

**安装门禁（L1，弱）**：`agentshield adapter install hermes` 生成 `~/.local/bin/hermes-skills-install` 包装脚本：先 `agentshield admit <src>`，非 quarantine 才调用真实 `hermes skills install`；SKILL.md 引导用户用包装脚本。本地放入 `~/.hermes/skills` 由 inventory 周期扫描（`serve` 每 5 分钟）发现未准入 Skill 并在 UI 标红。

**工具边界（grant 输出）**：写 `platform_toolset_modes` allowlist（Hermes siq-patches 支持闭世界模式）；写前备份。

### 4.3 CodeBuddy / WorkBuddy（P1）

**运行时（L2）**：`~/.codebuddy/settings.json` 追加（需用户确认，幂等）：

```json
{"hooks":{"PreToolUse":[{"matcher":".*","hooks":[{"type":"command","command":"<abs>/agentshield hook codebuddy","timeout":5}]}],
          "PostToolUse":[{"matcher":".*","hooks":[{"type":"command","command":"<abs>/agentshield hook codebuddy --observe","timeout":5}]}]}}
```

`agentshield hook codebuddy`：stdin 读 `{session_id, tool_name, tool_input, cwd, permission_mode}` → `/v1/decide` → stdout：

```json
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow|deny|ask","permissionDecisionReason":"..."}}
```

`hold → ask`、`deny → deny`、`redact` → 当前 CodeBuddy 不支持改参，退化为 `ask`。

不使用 Skill frontmatter hooks（仅 fork Skill 且默认关闭）。

### 4.4 Trae / TraeWork（P2，审计）

无钩子。SKILL.md 引导：安装前 `agentshield admit`；`serve` 周期扫描 `.trae/skills`；UI 标「审计模式，无法阻断」。`skill-manifest.support_matrix` 对应行 `status=audit_only, tiers=[L0]`。

### 4.5 适配器公共约定

- 只做 HTTP + 映射，不含任何判定逻辑、不含规则、不含密钥。
- 每个适配器附 `adapters/runtime/<x>/README.md`：安装、卸载、fail-closed 行为、已知限制。
- E2E 用例：装 → 扫 → 授 → 越权被拒，一条录屏 + 一份回执文件。

---

## 5. SKILL.md 与发布

### 5.1 `skills/agentshield/`

```
SKILL.md                 frontmatter: name agentshield, description ≤60 字符句号结尾,
                         allowed-tools（声明本 Skill 自身需要：terminal/read_file）, compatibility
scripts/bootstrap.sh     POSIX：定位/下载二进制 → 校验 manifest 签名与 sha256 → serve → 打印 UI URL
scripts/bootstrap.ps1    Windows 同上
scripts/adapter.sh       调用 agentshield adapter install <platform>（探测当前平台）
references/tiers.md      档位说明与各平台限制（给模型读，减少幻觉）
references/decision-table.md  §3.6.4 的精简版
evals/evals.json         SkillEvaluator 格式：装恶意 Skill 应 quarantine、官方 Skill 应 admit_with_conditions、越权应 deny
skill-card.md            本 Skill 自己的卡
skill-manifest.json      发布时生成并签名（schema: skill-manifest）
```

SKILL.md 正文结构：`# AgentShield Skill` / 简介 / When to Use / Prerequisites / How to Run（三步：bootstrap → adapter → 打开 UI）/ Quick Reference（子命令）/ Procedure（四个子 Skill 的调用顺序与「结果由二进制给出，不要自行判断」）/ Pitfalls（无钩子平台、fs 不热更新、Windows L3）/ Verification。

**模型行为约束写法**：正文明确「你（模型）不判断 Skill 是否安全；运行 `agentshield admit` 并原样呈现 verdict 与 Skill Card」。

### 5.2 发布流程（CI）

1. `go test ./...`、`go vet`、`gofmt`；Python 全量测试。
2. 交叉编译 `linux/{amd64,arm64}`、`darwin/arm64`、`windows/amd64`，`-ldflags "-X main.Version=<tag>"`，产出 sha256。
3. 计算 `skills/agentshield/` `content_hash`；生成 `skill-manifest.json`；用发布密钥（CI secret `AGENTSHIELD_RELEASE_SEED`）签名；bootstrap 脚本内置发布公钥。
4. 打 `agentshield-skill-<tag>.zip`（Skill 目录 + manifest）供 TraeWork 上传 / ClawHub / 手动安装；GitHub Release 挂二进制。
5. 自扫描：CI 用刚构建的二进制对 `skills/agentshield/` 跑 `admit`，必须为 `admit_with_conditions`（声明 terminal/network），不得 quarantine。

### 5.3 分发仓库

不新开（ADR-011 D5）。若市场要求根目录即 Skill，由 CI 镜像 `skills/agentshield/` 到分发仓，源码不迁出。

---

## 6. 安全模型（AgentShield 自身）

| 威胁 | 缓解 | 残余 |
| --- | --- | --- |
| 恶意 Skill 冒充 AgentShield 引导用户跑假二进制 | manifest 签名 + sha256 内置于 bootstrap；UI 显示公钥指纹 | 用户跳过校验 |
| 模型被注入后调用 `grant --approve` | CLI 批准需 `--approve-as` 且写 `channel`；UI 批准需人点；SKILL.md 禁止模型批准 | 模型仍可在终端执行 CLI —— 通过 grant 把 `agentshield grant approve` 本身列入 `require_approval`（自保护） |
| 适配器被绕过（Agent 用原生 HTTP 出网） | OpenShell 网络 default-deny（L3）；无 L3 时 UI 明示「仅工具层拦截」 | Mac/Win 无 Docker |
| 回执被改写 | 只追加 + 哈希链 + 签名；`verify` | 私钥泄露（状态目录被读）|
| 规则包被替换 | 外部包验签 + 防降级；内嵌包为基线 | 二进制本身被替换（由 manifest 校验覆盖）|
| 决策 API 被本机其他进程调用 | loopback + bearer token 0600 | 同用户下其他进程可读 token（OS 边界）|
| 参数/结果含密钥进入回执 | 只存摘要 + 脱敏 excerpt ≤512 | 未知密钥格式（黑名单固有局限）|
| Skill 扫描触发解压炸弹/巨文件 | §3.6.1 限额，超限 quarantine | — |

---

## 7. 测试计划

### 7.1 单元与对等

| 层 | 测试 | 状态 |
| --- | --- | --- |
| canon | CPython 固定向量 | 已有 |
| rulepack | 内嵌一致性、拒绝表、fail-closed 表、防降级 | 已有 |
| threat | 共用语料对等、规则全覆盖、crontab 改写、脱敏截断、类型识别 | 已有 |
| signing | 跨实现签名向量、O_EXCL、损坏 seed | 已有 |
| admission | 每条内置检查一正一负；决策表逐行；限额边界（恰好上限通过、+1 拒绝）；符号链接逃逸；frontmatter 解析矩阵 | W1 |
| grant | 每条转换映射；deny 覆盖 allow；重叠三态；状态机非法迁移拒绝；effective 无读回拒绝；与 Python `compile_policy` 的 `artifact_hash` 对等 | W1 |
| receipt | 链构造与 `verify`；每条决策算法分支；污点/trifecta；fail-closed 表；audit_only 不阻断 | W1 |

### 7.2 跨语言 schema 校验

Go 测试把 `admission/grant/receipt/skill-manifest` 样例写到 `apps/agentshield/testdata/contracts/*.json`（提交入库）；`apps/control-api/app/tests/test_schema_contracts.py` 新增用例读取这些文件并用 schema 校验。Go 侧测试断言运行时输出与提交样例一致（防漂移）。

### 7.3 负向语料与回归集

- `apps/agentshield/testdata/skills/malicious/*`：隐藏注释、零宽字符、同形字、`.env` + webhook、符号链接逃逸、超限 zip、SKILL.md 缺失 → 全部 quarantine。
- `apps/agentshield/testdata/skills/benign/*`：含 `allowed-tools`、`curl | sh` 安装步骤、references 里演示 `.env` → admit_with_conditions，且 **不得** quarantine。
- NVIDIA 官方 Skill 集（349 个，不入库，CI 可选 `git clone` 到临时目录）：quarantine 率报告写入 `detection-baseline.md`；目标 < 2%，逐条人工确认剩余项。

### 7.4 E2E（每平台一条）

装恶意 Skill → `admit` quarantine（L1 平台：安装被拒）→ 装官方 Skill → grant → 越权工具调用 → deny 回执 → `verify` 通过。录屏 + 回执文件归档到 `docs/evidence/agentshield/<platform>-<date>/`（脱敏）。

### 7.5 平台矩阵

`skill-manifest.support_matrix` 每一行至少一次真实运行证据；无证据的行标 `experimental`。

---

## 8. 开发流程

### 8.1 目录与模块

```
apps/agentshield/            Go module（stdlib only；go.work 引入 connectors/* 与 edge/agent/protocol）
  cmd/agentshield/
  internal/{canon,rulepack,threat,signing,inventory,admission,grant,receipt,openshell,ui,state}
  testdata/{contracts,skills}
adapters/runtime/{openclaw,hermes,codebuddy}-agentshield/
skills/agentshield/
packages/contracts/
```

### 8.2 命令

```bash
# Go
cd apps/agentshield && gofmt -l . && go vet ./... && go test ./...
for t in linux/amd64 linux/arm64 darwin/arm64 windows/amd64; do GOOS=${t%/*} GOARCH=${t#*/} go build ./cmd/agentshield; done
# Python（合同、规则包、基线）
cd apps/control-api && uv sync --dev --frozen && uv run --frozen ruff check app && uv run --frozen pytest -q
# 规则包变更：两侧都要跑
uv run --frozen pytest app/tests/test_threat_analysis.py app/tests/test_threat_rulepack.py app/tests/test_detection_baseline.py
(cd ../agentshield && go test ./internal/rulepack ./internal/threat)
# UI
cd apps/web && npm ci && npm run build
```

### 8.3 规则

- 合同先行：改 `packages/contracts/` → 补负向测试 → 改 Go/Python。
- 规则包是共享文件：改一处同步另一处（测试锁定），模式必须 RE2 兼容且 CPython 语义等价，附边界用例。
- 提交格式 `<scope>: <主题>`：`contracts:`、`agentshield:`、`adapters:`、`skills:`、`rulepack:`、`docs:`。
- 每个安全相关修复带负向测试。
- 不在 `apps/agentshield` 引入第三方依赖，除非 ADR 批准（tree-sitter 属此类）。

### 8.4 分支与 PR 顺序

| PR | 内容 | 状态 |
| --- | --- | --- |
| #2 | 调研 + ADR-011 + 设计方案 | draft |
| #3 | W0 合同 + W1（canon/rulepack/threat/signing/CLI）+ 本规格 | draft，叠在 #2 |
| 后续 | W1 余量（admission/grant/receipt）、W2 UI、W3 适配器、W4 OpenShell、W5 Skill 包、W6 材料 | 各自 PR，叠加或在 #3 合并后基于 main |

---

## 9. 里程碑与进度（2026-09-04）

| 阶段 | 内容 | 进度 |
| --- | --- | --- |
| W0 合同 | 四 schema + 42 负向测试 + README + 兼容矩阵 | **完成** |
| W1 Go 核心 | canon / rulepack / threat / signing / CLI | **完成**；admission / grant / receipt **未开始** |
| W2 二进制与 UI | serve、状态目录、embed UI、三 OS 构建 | 未开始（三 OS 交叉编译已验证）|
| W3 适配器 | OpenClaw、Hermes、CodeBuddy | 未开始 |
| W4 OpenShell | probe / 网络 policy set / 读回 | 未开始 |
| W5 Skill 包 | SKILL.md、bootstrap、evals、manifest、release | 未开始（备份中的 `skill-admission` 规范目录可迁入）|
| W6 材料 | README、演示、基线更新、十日谈 | 未开始 |

---

## 10. 开放问题

1. **AST 层**：tree-sitter（cgo，破坏纯 stdlib 与交叉编译便利）vs 纯 Go 词法（只识别 `os.system(`、`shell=True`、`ctypes.` 模式，接近正则）。倾向后者作为 v1.1，正式 AST 留控制面。
2. **`candidate.source_type` 增 `skill_dir`**：合同升版（v1 → 追加 enum 属非破坏，但需同步 Edge/Web types）。
3. **Hermes hold 语义**：无 approval 通道，退化为 block + URL；是否值得给 Hermes 提一个 `pre_tool_call` 返回 `ask` 的上游 PR。
4. **StepFun 云端路由**：`model_routing` 在 OpenShell 走 `inference.local`，脱敏 broker 是否复用 research-engine 的 provider 合同（只读参考，不依赖）。
5. **训练营 9/20 工具包**：若 NVIDIA 发布 OMS 签名工具链，`skill-manifest.signed_by` 是否切换到证书链（当前 Ed25519 本地信任根）。
