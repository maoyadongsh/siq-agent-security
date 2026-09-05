# AgentShield 开发规格 v1（Development Specification）

- 日期：2026-09-04
- 状态：**生效**；实现必须以本文为准，偏离先改本文再改代码
- 上游文档：ADR-011（决策）→ `agentshield-design-v1.md`（方案）→ **本文（规格）** → `packages/contracts/`（合同事实源）
- 相关：`research/agentshield-market-survey-2026-09.md`、`detection-baseline.md`、`compatibility.md`、ADR-003/004/005
- W7 增量计划（本地台账与企业能力对齐，待按期回写本文）：[`agentshield-local-ledger-dev-plan-v1.md`](./agentshield-local-ledger-dev-plan-v1.md)

> 文档分工：设计方案回答「做什么、为什么」；本文回答「怎么做、边界在哪、怎么验证」。合同细节以 schema 为准，本文只解释语义与算法，不复制字段表。W7 新接口与状态文件必须先回写本文再实现。

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
                                              ├─ export      ─► 脱敏包 agentshield.export.v1
                                              ├─ sync        ─► 可选 Edge batch（默认不跑）
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
  assets/<file_id>.<seq>.json   纳管投影（confirm/dismiss/stale）；不改写
  findings/<file_id>.<seq>.json 漂移 finding 与风险接受覆盖；不改写
  audit.jsonl                  操作审计（admit/grant/revoke/adapter/confirm/dismiss/accept）；无密钥无参数原文
  logs/agentshield.log     类别级日志，无内容
```

目录 0700，文件 0600（Windows 不检查 POSIX 位，依赖用户目录 ACL）。

### 2.3 并发

- 单写者：`serve` 持有 `<state>/serve.lock`（O_EXCL 创建，内含 pid；启动时若 pid 不存活则接管）。
- 子命令（`admit`/`grant`）与 `serve` 同时运行时，通过 HTTP 提交给 `serve` 写入；`serve` 未运行则子命令直接写文件。
- 回执链：`serve` 内存持有 `(seq, hash)`；写入顺序 = 先 append 行、`fsync`、再更新 `HEAD`。恢复时以文件最后一行为准，`HEAD` 只是加速。

### 2.4 与控制面同步（可选，非现场）

`agentshield sync --control-api <url>`：把最新盘点的 **candidates + evidence** 按现有 Edge `POST /edge/v1/batches` 追加上传（不传 `permission_facts`，避免 `agent_asset` 主体对不上 candidate_id，也禁止自报 `effective`）。本地是事实源：**`serve` 从不自动 sync**；缺 Edge 凭据则跳过并退出 0；HTTP/验签失败退出非 0 且 **不写** admissions/grants/receipts。凭据来自 `--identity` / `--secret-file` / `--task-id`，或环境变量 `SIQ_AS_EDGE_IDENTITY`、`SIQ_AS_EDGE_SECRET`、`SIQ_AS_EDGE_TASK_ID`。上传前刷新 `collected_at` 并把 `collector_id` 写成设备身份后用本地 Ed25519 重签；控制面仍用已登记的 Edge 公钥验签（须把本机 `agentshield pubkey` 登记为该设备）。回执链本身不进 Edge batch，评委导出走 §3.8.1 `GET /v1/export`。

现场主界面是内嵌本地台账（§3.10），不依赖本同步、不依赖 PostgreSQL / `:8600`。P0 为只读投影；P1 起写入 `assets/`（确认/驳回/stale）；P2 写入漂移 finding；接受覆盖与 `audit.jsonl` 随 P1/P2 落地。P3 增加脱敏导出包。`sync --control-api` 仍非现场、默认不跑。

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
| MCP 配置 | 原生只读众所周知客户端配置（`~/.cursor/mcp.json`、`~/.claude.json`、`~/.claude/mcp.json`、`~/.windsurf/mcp_config.json`、`~/.codeium/windsurf/mcp_config.json`）：只留 `env_keys`、`scheme://host`、command 基名；不连接、不 exec | candidate（mcp_server）|

**输出**：`inventory/<ts>.json`，内容符合 `candidate.schema.json` + `evidence.schema.json`；每条 candidate 至少引用 1 条 evidence；`.env`/`auth-profiles`/`apiKey` 类字段只出 `secret_ref` 或 `size`。

**新增（相对现有 Connector）**：Skill 目录扫描——每个 `SKILL.md` 产出 candidate `source_type=skill_dir`（需在 `candidate.schema.json` enum 增加 `skill_dir`，合同升版），附 `content_hash` 与是否已有 admission 记录。

**实现方式（2026-09-04 修正）**：`connectors/*` 全部是 `package main` 的 NDJSON 子进程，不能作为库导入。inventory 用 Go **原生只读发现**，产出 `platform_config` / `skill_dir` / `hermes_profile` / `openclaw_agent` / `mcp_server` 候选。可选 `--connectors-dir`（或 `SIQ_AS_CONNECTORS_DIR`）：对 `hermes` / `openclaw` / `directory` / `mcp` **exec** `--serve`，超时 60s、stdout 上限 8MB；`describe.network_access=true` 或失败记入 `skipped`，不阻断原生结果。合同：`candidate.source_type` 已含上述枚举。

**实现状态（相对本表）**：

| 项 | 状态 |
| --- | --- |
| 平台配置存在性 + Skill 目录 `SKILL.md` | **已完成** |
| Hermes `profiles/*/`（`config.yaml` 或 `SOUL.md`）各一条 `hermes_profile`；`platform_toolsets`/`toolsets` → tool 域 declared | **P1** |
| `~/.hermes/config.yaml` 的 `platform_toolset_modes` 键（只读，不执行） | **P1** |
| OpenClaw `agents.list`（密钥值不出结构体；不读 `auth-profiles` 正文） | **P1** |
| MCP 众所周知客户端配置只读（`mcp_server`；不连接、不 exec command；env 只出键名；url 只留 `scheme://host`；符号链接/畸形 JSON 记 `skipped`） | **已完成** |
| 可选 `--connectors-dir` exec（含 `connectors/mcp`） | **已完成**（P3；默认不跑） |
| k8s / docker 舰队扫描 | **未做**（默认不扫） |

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
| 内置 | `adm-credential-path`：`SKILL.md` / `scripts/` 引用 `.env`、`.ssh/`、`id_rsa` 等凭据路径 | credential_exfil | **同文件有出网槽 → quarantine**；否则 declare（`credential.read`）| 规则包 `threat-cred-*` 偏 shell；本检查覆盖 `open()` / `ReadFile` 等 |
| 内置 | `adm-writes-outside-skill`：脚本写入 `~`、`/etc`、`$HOME`、`%APPDATA%` 等 | capability_declaration | declare（`filesystem.write`）| |
| 内置 | `adm-binary-file`：非文本文件 | supply_chain | info（计入 `binary_files`）；可执行位或 `.exe/.so/.dll` → declare `process.exec` | |
| 内置 | `adm-symlink-escape` / `adm-over-limit` / `adm-skill-md-missing` / `adm-manifest-mismatch` | integrity | **quarantine** | 候选目录自带 `skill.manifest.json` 的 per-file sha256 与实文件不一致时隔离；无 manifest 不是 finding |
| 内置 | `adm-name-mismatch` / `adm-name-invalid`：frontmatter `name` 与目录名不一致或违反 agentskills 规则 | info | info | |

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
| `GET /ui-config.json` | loopback 无鉴权：token + version + mode，供控制台内存持有；禁止 localStorage |
| `GET /v1/inventory` | 盘点（POST 仍可用，body.cwd 或 `?cwd=`）|
| `GET`/`PUT /v1/config` | 读/写 `enforcement_mode`（热更新 Engine）|
| `GET /v1/adapter/status` `POST /v1/adapter/install` `POST /v1/adapter/uninstall` | 控制台装/卸适配器 |
| `GET /v1/openshell/probe` | OpenShell L3 探测；失败时附 `doctor` |
| `GET /v1/openshell/doctor` | OpenShell 诊断（不启动网关；`started_gateway` 恒 false） |
| `POST /v1/openshell/apply` | 仅网络段 `policy set` + 读回 |
| `GET /v1/assets` | 最新盘点与 `assets/` 状态机的合并列表（`?cwd=` 同 inventory） |
| `GET /v1/assets/{id}` | 资产详情。`id` 为 `candidate_id`（URL 解码） |
| `POST /v1/assets/{id}/confirm` | 写入 confirmed；body `actor_id` 必填 |
| `POST /v1/assets/{id}/dismiss` | body：`actor_id`、`reason`、`until`（RFC3339）均必填；缺一 4xx |
| `GET /v1/permissions` | 五态聚合；`?subject_id=` 可选过滤。**不得**把 `deployed` grant 显示为 `effective` |
| `POST /v1/grants/{id}/patch-desired` | 五域补丁；仅 `pending_approval`。filesystem/process 写入则标 `static_domains_unavailable`；补丁后仍须人批 |
| `GET /v1/findings` | 准入 finding 投影 + 已持久化漂移/接受覆盖 |
| `POST /v1/findings/{id}/accept` | body：`actor_id` + `reason` + `until` 必填；到期后 GET 视为 open |
| `POST /v1/openshell/drift-check` | 读回 vs 已部署 grant 的 network 段；不一致写 finding。网关/CLI 失败 **5xx** 且 **不**写「无漂移」 |
| `GET /v1/audit` | 最近操作（无密钥、无参数原文） |
| `GET /v1/export` | 脱敏导出包 `agentshield.export.v1`（无 token、无私钥、无参数原文、无 Skill 正文） |

#### 3.8.1.1 五态聚合（P0）

`GET /v1/permissions` 由 `internal/ledger` 从已有 admission / grant / receipt / inventory fact 投影，不新写 STATE_DIR。

| state | 唯一合法来源 |
| --- | --- |
| declared | admission `declared_facts`；grant 中 `state=declared` 的事实（无 grant 时才直接展示 admission，避免重复） |
| inferred | grant 中 `state=inferred` 的事实 |
| observed | receipt 每次工具调用（`domain=tool`，`action=allow\|deny\|hold\|redact`）；inventory 适配器挂钩 fact |
| effective | **仅** grant 事实已是 `state=effective` 且带读回 revision（OpenShell `MarkEffective`）。`deployed` ≠ `effective` |
| unknown | grant `static_domains_unavailable` 中的域（filesystem/process），且该域没有 effective 事实 |

filesystem / process 即使误标 `effective`，本端点也必须降为 `declared` 或 `inferred`（以 grant 原态为准，禁止输出 `effective`）。

#### 3.8.1.2 资产生命周期与 G7（P1）

`GET /v1/assets` 合并最新 inventory 与 `<state>/assets/` 最新版本。文件名是 `ast-<sha256(candidate_id)[:16]>.<seq>.json`（`safeID` 不含 `:`/`@`）；JSON 内仍保存原始 `candidate_id`。0600，只新建版本。

| 存储 status | 含义 |
| --- | --- |
| `candidate` / `unadmitted` / `admitted` / `quarantined` | 与 P0 投影一致（Skill 未准入仍可见） |
| `confirmed` | 人类确认纳管 |
| `dismissed` | 驳回；须 `reason` + `until`；到期后下次 refresh 回到 `candidate`（Skill 则为 `unadmitted`） |
| `needs_review` | 哈希变化或钩子丢失 |
| `stale` | 目录/配置消失；列表仍展示存储记录 |

G7（`serve` 约 5 分钟及每次台账 GET 的 refresh）：

| 事件 | 行为 |
| --- | --- |
| 已准入 Skill `content_hash` 变化 | 新候选 `needs_review`；旧行 `stale`；旧 grant → `revoked`（`grant.Revoke` + 新版本）；不自动新建 admission |
| Skill 目录消失 | 资产 `stale`；已部署 grant revoke |
| 适配器/钩子从配置消失 | 该平台档位 L0（既有 `adapterinstall.Status`）；资产 `needs_review` 且 `hook_lost=true`；文案「发现得到、当前无法阻断」 |
| `dismiss_until` 过期 | 回到 `candidate` / `unadmitted` |

`POST /v1/openshell/drift-check`：仅已验明 L3。对 `deployed`/`effective` grant 的 network 段做 `policy get --full` 比对；不一致写入 `findings/`（`source=drift`）。CLI/网关失败 **5xx**，**不得**写「无漂移」finding。

#### 3.8.1.3 脱敏导出（P3）

`GET /v1/export` 与 `agentshield export [--out FILE]` 产出同一 JSON（`format=agentshield.export.v1`）：

- 含：公钥、enforcement_mode、资产摘要、准入 verdict/哈希/finding 规则、grant 状态与事实摘要、回执（seq/action/tool/reason/hash，**不含** `params` / `params_excerpt`）、`audit.jsonl` 尾部、回执链 `verify` 结果。
- 不含：token、signing seed、私钥、Skill 文件正文、环境变量、OpenShell 密钥。
- CLI 写文件 0600。控制台设置页可下载。失败不得把密钥写进错误字符串。

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
   b. 出网类工具（exec 含 curl/wget/nc、web_fetch、http、send_message、browser）解析目标 host → 不在 grant network allow → deny。**block 模式**：shell 工具只要命令匹配出网程序（curl/wget/nc/…），即使未解析到 host，也 deny（`egress exec requires granted host`），除非 grant 对该次解析到的 host 显式 allow。warn/audit_only 不因此条额外 deny。
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

- 后端只用 CLI。显式环境变量与 Python `cli_backend.py` 相同：`SIQ_AS_OPENSHELL_CLI_BIN` 与 `SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT`（必须成对）或 `SIQ_AS_OPENSHELL_ENV_SH`。`ENV_SH` 在 `source` 之后优先 `exec $SIQ_OPENSHELL_BIN`（research-engine `env.sh` 约定），否则 PATH 上的 `openshell`。
- AgentShield 额外发现 PATH 上的 `openshell`，走用户 CLI 配置（`HOME` / XDG / `OPENSHELL_*`），不注入 `--gateway-endpoint`。显式 `SIQ_AS_*` 优先于 PATH。Python 控制面后端不跟随此发现。
- `probe()`：`gateway info` 只表示调用了 OpenShell CLI（本地配置打印，端口上即使是 OpenClaw 也可能 rc=0）。必须以 `status`（或等价的会真正连网关的命令）做握手。`status` 出现 `InvalidContentType` / OpenClaw / Hermes 特征则 fail-closed。不按版本号假设能力。禁止猜测端口，禁止改别人的网关。
- **禁止** `openshell gateway start`。bootstrap、doctor、serve 都不启动网关。缺 CLI、网关没起、连错进程时 L0–L2 照常，并给出人类可执行修复。
- `agentshield openshell doctor` 与 `GET /v1/openshell/doctor`：报告 CLI 路径、覆盖来源（`env_pair` / `env_sh` / `path` / `none`）、探针、身份、`human_next`；`started_gateway` 恒为 `false`。
- `apply(network)`：`policy set` 只提交网络段；`policy get --full` 读回 → 比对 → 产出 `effective_readback{backend:"openshell", revision}` 与 evidence。
- 不调用 `create_generation`；fs/process 段写入 `sandbox create` 时的策略文件（静态），并在 grant 里标 `static_domains_unavailable`。
- macOS/Windows：`probe()` 失败（无 Docker/WSL2）→ L3 不可用，UI 显示原因。

### 3.10 `internal/ui`（规格）

- 复用 `apps/web` **设计系统**（`index.css`、PageHeader、SimpleTable、icons、Layout 磨砂侧栏），**不要**把本地页塞进企业控制台的 `AuthGate` / JWT 路由。
- 第二入口：`index.local.html` + `src/local/`；`npm run build:local`（`VITE_APP=agentshield`）写入 `apps/agentshield/internal/ui/embedded/`，Go `embed` 进二进制。`make -C apps/agentshield ui` 先跑 `npm ci && npm run build:local`。
- 企业控制台（`index.html` + `src/App.tsx`，对接 Control API `:8600`）保持独立；`npm run build` 行为不变。
- 页面（W7 P0 台账 IA；企业 `/agents` 观感，数据仍走本地 `/v1/*`）：

| 路由 | 标题 | 数据 |
| --- | --- | --- |
| `/overview` | 总览 | 档位、链头、未准入 Skill 数、最近 deny |
| `/agents` | 智能体资产 | `GET /v1/assets`；详情 `/agents/:id` |
| `/permissions` | 权限视图 | `GET /v1/permissions` 五态分色 |
| `/findings` | 风险中心 | `GET /v1/findings`；接受须 reason + until |
| `/grants` | 签发 | 现有 grant 审批 |
| `/receipts` | 回执 | 现有链；deny 高亮；验签 |
| `/bindings` | 运行时绑定 | 适配器 status + OpenShell probe 摘要 |
| `/settings` | 设置 | enforcement_mode、actor、OpenShell apply、操作审计、脱敏导出 |

- 兼容重定向：`/inventory`、`/admissions` → `/agents`。顶栏常驻标签：**「本地模式 · 单用户」** + 当前平台档位（如 `OpenClaw · L2 · 仅工具层拦截` / `Trae · 审计模式，无法阻断`）。无 OpenShell L3 时，L2 必须带「仅工具层拦截」。L3 仅在 OpenShell probe 成功后显示。
- 资产详情：确认 / 驳回（reason+until）；`pending_approval` grant 可编辑五域后 `patch-desired`（fs/process 标静态不可用）。权限页：有 L3 才启用漂移检测，否则禁用并写原因。绑定页可装/卸适配器。
- 所有写操作走 §3.8.1 端点并带 token；UI 无私钥。Token 由 `GET /ui-config.json`（仅 loopback）进入内存，禁止 `localStorage` / 地址栏 `?token=`。

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

操作清单（tag 未切前 URL 对象不存在；bootstrap 不下载）：[`agentshield-release-checklist-v1.md`](./agentshield-release-checklist-v1.md)。哈希核对脚本 `scripts/agentshield-release-check.sh` 不需要种子；重签需要 `AGENTSHIELD_RELEASE_SEED`。矩阵不得出现 `supported` 行。

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

已归档（linux/arm64，矩阵仍无 `supported`）：Hermes 实机插件；OpenClaw 隔离 HOME 的 `policy-exec` + 插件形态 `/v1/decide`；CodeBuddy 隔离 HOME 的真实 `hook codebuddy`。OpenClaw 未挂到本机网关进程；CodeBuddy 未驱动 GUI。

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
# UI（AgentShield 本地控制台；企业控制台仍是 npm run build）
cd apps/web && npm ci && npm run build:local
make -C apps/agentshield ui
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
| W1 Go 核心 | canon / rulepack / threat / signing / admission / grant / receipt / CLI | **完成**；每个模块的 Go 样例均回灌 Python schema 校验；grant 的 `artifact_hash` 与 Python 编译器一致 |
| W2 二进制与 UI | serve、状态目录、embed UI、三 OS 构建 | `state` 包 + `serve` **完成**；HTTP E2E **完成**；`inventory` **完成**；embed UI **完成**（`src/local/` + `internal/ui`） |
| W3 适配器 | OpenClaw、Hermes、CodeBuddy | Hermes 插件 **完成**；OpenClaw `policy-exec` **完成**；CodeBuddy `hook codebuddy` **完成**；`adapter install/uninstall`（备份还原）**完成** |
| W4 OpenShell | probe / 网络 policy set / 读回 | **完成**（CLI 后端 + PATH/ENV_SH 发现 + 网关验明 + `openshell doctor` + `/v1/openshell/*` + 控制台 L3；假 CLI 正负测试。矩阵不标 `supported`） |
| W5 Skill 包 | SKILL.md、bootstrap、evals、manifest、release | **完成**（Skill 目录、evals、bootstrap 验签、`grant` CLI、自扫描不得 quarantine、已签名 `skill-manifest.json` + 四目标哈希。GitHub Release `agentshield-v0.1.0` 已挂二进制；bootstrap 仍不下载。矩阵仍无 `supported` 行） |
| W6 材料 | README、演示、基线更新、十日谈 | **完成**：评委入口 `AGENTSHIELD.md` + 演示步骤；2026-09-05 Spark linux 证据已归档：Hermes 实机插件、OpenClaw `policy-exec`、CodeBuddy `hook`（隔离 HOME）。矩阵备注已对齐证据，**仍无 `supported` 行**。Release tag 已切（清单 [`agentshield-release-checklist-v1.md`](./agentshield-release-checklist-v1.md)）。L3 可选：须验明正身的 OpenShell |
| W7 本地台账 | 企业治理语义在本地文件态落地（资产/五态权限/风险/漂移/导出）；Control API 仍非现场依赖 | **P0–P3 已落地**（§2.4 / §3.5 / §3.8.1 / §3.10）：assets 状态机、profiles/agents.list、五域补丁、漂移、exec 无 host deny、findings 接受、audit.jsonl、脱敏导出、`sync --control-api`（默认不跑）、可选 `--connectors-dir`、MCP 配置原生只读（`mcp_server`）。矩阵仍无 `supported` 行 |

---

## 10. 开放问题

1. **AST 层**：tree-sitter（cgo，破坏纯 stdlib 与交叉编译便利）vs 纯 Go 词法（只识别 `os.system(`、`shell=True`、`ctypes.` 模式，接近正则）。倾向后者作为 v1.1，正式 AST 留控制面。
2. **`candidate.source_type` 增 `skill_dir`**：合同升版（v1 → 追加 enum 属非破坏，但需同步 Edge/Web types）。
3. **Hermes hold 语义**：无 approval 通道，退化为 block + URL；是否值得给 Hermes 提一个 `pre_tool_call` 返回 `ask` 的上游 PR。
4. **StepFun 云端路由**：`model_routing` 在 OpenShell 走 `inference.local`，脱敏 broker 是否复用 research-engine 的 provider 合同（只读参考，不依赖）。
5. **训练营 9/20 工具包**：若 NVIDIA 发布 OMS 签名工具链，`skill-manifest.signed_by` 是否切换到证书链（当前 Ed25519 本地信任根）。
