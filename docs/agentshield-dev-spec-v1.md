# siq-agent-security 开发规格 v1（Development Specification）

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
SKILL.md ──(1) 校验 manifest 与二进制哈希──► siq-agent-security 二进制
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
| 二进制 → 规则包 | 内嵌包为基线；外部包需 `SIQ_AGENT_SECURITY_RULEPACK_PUBKEY` 验签 | Ed25519 over canonical JSON；版本 ≥ 内嵌 | 回退内嵌包，stderr 记类别 |
| 适配器 → 决策 API | 状态目录内 `token`（0600） | `Authorization: Bearer <token>`；只监听 127.0.0.1；**仅** `/v1/decide` 与 `/v1/observe` | 401；管理端点对该凭据返回 403；适配器按 fail-closed 表处理 |
| 控制台 → 管理 API | serve 启动时的一次性配对码 → 有期限管理会话 | `POST /v1/pair` 后 `Authorization: Bearer <session>`；Host 仅 `127.0.0.1`/`localhost`/`::1` + 监听端口；写操作拒绝非法 Origin / `Sec-Fetch-Site: cross-site` | 401/403；无认证配置接口不含 secret |
| 回执 → 阅读者 | 本地 Ed25519 身份（`keys/signing.seed`） | `siq-agent-security verify` 重算哈希链并验签 | 报告首个断链/坏签位置 |
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
| Linux | `$XDG_STATE_HOME/siq-agent-security`，否则 `~/.local/state/siq-agent-security` | `SIQ_AGENT_SECURITY_STATE_DIR` |
| macOS | `~/Library/Application Support/siq-agent-security` | 同上 |
| Windows | `%LOCALAPPDATA%\siq-agent-security` | 同上 |

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

- 单写者：`serve` 通过 `state.AcquireWriter` 持有 `<state>/serve.lock`（O_EXCL；内含 pid/owner；启动时若 pid 不存活则将旧锁 rename 为 `serve.lock.stale.*` 后接管，禁止无条件删除）。离线 `grant` 子命令须取得同一写锁；锁被存活 `serve` 占用时拒绝直写。
- 子命令（`admit`/`grant`）与 `serve` 同时运行时，通过 HTTP 提交给 `serve` 写入；`serve` 未运行则子命令在写锁下直接写文件。
- 回执链：`serve` 内存持有 `(seq, hash)`；写入顺序 = 先 append 行、`fsync`、再更新 `HEAD`。恢复时以文件最后一行为准，`HEAD` 只是加速。
- 不可变版本按 ADR-012 先在同目录私有暂存文件完成写入/Sync，再排他发布最终版本名；版本占用只允许重试下一序号，不能返回伪成功。读者不得看见未完成暂存或把损坏最新版本忽略为空。
- grant 状态变迁（approve/reject/deploy/revoke/patch-desired/effective/resolve-overlap）必须带 `expected_revision`（当前磁盘版本序号）；冲突返回 409，不得静默追加成功。创建响应与 `GET /v1/grants/{id}` 返回 `state_revision`。该 CAS 不替代多文档审计事务（DEV03）。
- **高影响批准（DEV02-B）：** `approve` 前须 `POST /v1/grants/{id}/challenge` 取得单次 `challenge_id`+`nonce`；挑战绑定 grant digest、scope digest、subject/platform 与 `expected_revision`，TTL 5 分钟，消费后不可重放。grant 正文或 desired 变更会使 digest 失配。desktop-same-uid 下挑战不是 OS 隔离边界，不宣称防止同 UID 自批。
- 审批状态转换先校验 actor 与未解决 overlap，再消费挑战。缺 actor 或 overlap 未解决时返回 HTTP 400；不追加 Grant 版本或成功审批审计，也不消费挑战。挑战成功消费后的持久化故障仍遵循既有提交恢复协议，不将整个审批流程宣称为跨文件事务。
- **多文档提交（DEV03-E）：** 在原单写者/CAS 上，`commits/<grant_id>.<seq>.prepare.json` 先持久化 `grant_commit/v1` 完整材料（已签 grant 原文、expected revision、可选 policy、审计）；随后排他发布 policy、`commit-audit/<id>.json`、grant 版本，最后写与 prepare SHA-256 绑定的 `.done.json`。`.done` 是可见性界限；未完成的当前或下一版本使 grant 读取失败关闭，不能继续沿用旧批准。`TailAudit` 合并历史 JSONL 与已提交的独立审计，不重复追加。所有写入采用同目录暂存+Sync+Link，Linux 同步目录；不支持目录 Sync 的 Windows 仅声明进程崩溃恢复，不声明断电保证。`serve`/离线 grant 获写锁后先恢复；`incomplete` 只读诊断，`incomplete --recover` 获同一写锁后幂等补齐，无新批准/后端副作用。旧 `.incomplete.json` 缺完整材料时保留且拒绝自动猜测恢复。升级前备份 state；不得用不理解 prepare/done 的旧二进制混跑或回退写入。
- **发布 staging（DEV04-D）：** bootstrap/adapter 经 `resolve_verified_bin.sh` 在验签后将二进制复制到私有 staging（0700），对副本再算 sha256；与源摘要（及 pin，若强制）不一致则拒绝。stdout 仅输出 staged 路径。不宣称同 UID 进程无法在验证后改写。真实下载链另做。

### 2.4 与控制面同步（可选，非现场）

`siq-agent-security sync --control-api <url>`：把最新盘点的 **candidates + evidence** 按现有 Edge `POST /edge/v1/batches` 追加上传（不传 `permission_facts`，避免 `agent_asset` 主体对不上 candidate_id，也禁止自报 `effective`）。本地是事实源：**`serve` 从不自动 sync**；缺 Edge 凭据则跳过并退出 0；HTTP/验签失败退出非 0 且 **不写** admissions/grants/receipts。凭据来自 `--identity` / `--secret-file` / `--task-id`，或环境变量 `SIQ_AS_EDGE_IDENTITY`、`SIQ_AS_EDGE_SECRET`、`SIQ_AS_EDGE_TASK_ID`。上传前刷新 `collected_at` 并把 `collector_id` 写成设备身份后用本地 Ed25519 重签；控制面仍用已登记的 Edge 公钥验签（须把本机 `siq-agent-security pubkey` 登记为该设备）。回执链本身不进 Edge batch，评委导出走 §3.8.1 `GET /v1/export`。

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
- 仅普通文件可被读取；根内链接的目标也必须是普通文件。FIFO、设备、socket 等类型直接返回受控错误。读取按剩余总字节预算加 1 字节探测，记录实际字节数；超过预算的准入显示 over_limit，HashDir/发布/盘点不得把不完整或越界树当完整哈希。稳定树的根内普通文件链接仍合法。**打开契约（ADR-013 / DEV05-C）：** 打开后对 fd 再 Stat，须仍为普通文件且 `SameFile` 与打开前一致；Unix 使用 `O_NOFOLLOW|O_NONBLOCK` 降低 symlink 替换与 FIFO 阻塞。不宣称同 UID 零窗口或 Windows 特殊文件完整矩阵。

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

每条 finding 与每条 declared 事实引用 ≥1 evidence：`evidence_id = ev-<sha256(path + line + rule_id + source.locator)[:16]>`，`source_type=manifest`，`content_hash` = 命中行脱敏前 sha256，`classification=internal`，`signature` 由本地 key 签。locator 进入 ID，避免不同 Skill 的相对路径命中共用同一文件名。evidence 写 `evidence/`。同一 `evidence_id` 再次写入时，仅当 `content_hash` 与 `source_locator` 一致才视为幂等；字节不完全相同也不得覆盖。

#### 3.6.6 输出

- `admissions/<admission_id>.json`（符合 `admission.schema.json`，`signature` 覆盖去签名后的规范化文档）。
- `admissions/<admission_id>.skill-card.md`：NVIDIA 最小卡结构（Description / Owner / License / Use Case / Requirements / Known Risks and Mitigations / References / Output / Version / Ethical）。Owner、License、Use Case 取 frontmatter，缺失写 `[unknown]`；Known Risks 由 declared 事实与 finding 生成可执行陈述（「该 Skill 会向 api.github.com:443 发起 HTTPS 请求；grant 未放行前被拒」）。页脚固定：**「本卡由 siq-agent-security 生成，不构成签名、批准或发布。」**
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

- 监听 `127.0.0.1:<port>`（默认 47611，`config.json` 可改）；拒绝非 loopback 远端地址。`Host` 必须是 `127.0.0.1` / `localhost` / `::1` 且端口与监听端口一致，否则 403（DNS rebinding 工程控制；完整浏览器链见 DEV18 记录）。
- 认证分权：
  - 决策：`Authorization: Bearer <token>`，token 文件仅 0600，适配器安装时读取一次；**只**接受于 `POST /v1/decide` 与 `POST /v1/observe`。
  - 管理：浏览器经 `POST /v1/pair` 用启动配对码换取有期限会话；CLI 写文件或带管理会话调用。决策 token 调用管理端点 → 403。
  - 配对：尝试预算 5、TTL 5 分钟、单次消费；凭据不进 `/ui-config.json`、localStorage、URL 或日志。
- 非浏览器 CLI：不发送 `Origin` / `Sec-Fetch-Site` 的已认证请求视为 CLI；浏览器写操作必须同源。Fetch Metadata 只作辅助。
- 桌面 profile 为 `desktop-same-uid`：同 UID 进程仍可读状态目录并执行 CLI 批准。不宣称防止被注入 Agent 自批；受管身份隔离是后续 Linux 配置。能力与证明强度见 [`agentshield-capability-profiles-v1.md`](agentshield-capability-profiles-v1.md)。
- 端点：

| 方法 路径 | 用途 |
| --- | --- |
| `POST /v1/decide` | 工具调用决策（同步）|
| `POST /v1/observe` | 工具结果观测（after/post 钩子；用于污点更新，不做决策）|
| `POST /v1/hold/{receipt_id}` | 人工签核（body: `{"approve": bool, "actor_id": ...}`；拒绝未知字段）。同一决议幂等返回已有回执；相反决议 409；超过 `hold.timeout_ms` 拒绝。 |
| `GET /v1/receipts?chain=&since_seq=` | 分页读回执 |
| `GET /v1/status` | 版本、enforcement_mode、平台档位、链头 |
| `POST /v1/admit` / `POST /v1/grant/...` | 控制台与 CLI 复用；同 §3.6/§3.7 |
| `GET /` | 内嵌 UI |
| `POST /v1/pair` | 一次性配对码换管理会话；无 secret 的 bootstrap |
| `GET /ui-config.json` | loopback 无鉴权：version + mode + `trust_profile` + `pairing_required`；**禁止**返回 token/session |
| `GET /v1/inventory` | 盘点（POST 仍可用，body.cwd 或 `?cwd=`）|
| `GET`/`PUT /v1/config` | 读/写 `enforcement_mode`（热更新 Engine）|
| `GET /v1/adapter/status` `POST /v1/adapter/install` `POST /v1/adapter/uninstall` | 控制台装/卸适配器 |
| `GET /v1/adapter/diagnostics` | admin 只读接入配置诊断，合同 `local-adapter-diagnostics/v1`；见 ADR-021，文件存在不再授予运行验证档位 |
| `POST /v1/adapter/preview` | admin 接入安装/卸载变更预览；`local-adapter-plan/v1`，后续应用必须绑定该会话的 plan_id/digest；ADR-022 |
| GET | `/v1/adapter/instances?platform=hermes` | 管理会话只读列举具体 Hermes profile，自定义根与默认根分别定位，返回 `local-adapter-instances/v1`（ADR-023）。 |
| POST | `/v1/adapter/recover` | 管理会话显式恢复中断的配置操作；仅回滚仍匹配本操作写入的文件，保留外部修改，不继续安装（ADR-022）。 |
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

`patch-desired` 重建平台工具策略时，必须从补丁后仍存在的事实重新派生 OpenClaw 的逐次审批限制，与初始 Grant Build 一致：process、resource（package.install）、credential 事实均使 `exec` 保持 `require_approval`。修改其他域或显式保留 `exec` 工具 allow 不得抹掉这项限制；凭据 deny 事实仍保留。审批限制由当前事实推导，不直接复制旧策略中的过期条目。该要求不把 `declared`/`deployed` 提升为 `effective`。

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

个人体验增量（ADR-021）：上述旧平台档位展示由实际证据限定；插件文件存在只说明安装痕迹。平台 HTTP 响应附 diagnosis，未获得当前实例正常/执行前拒绝自检证据时保持运行状态 unverified 和 L0，不以 installed 自动提升到 L2。此变化不改写历史 Grant 或回执，也不等同于自动撤销权限；具体配置漂移触发与运行验证生命周期继续按 UX-006 实施。

#### 3.8.1.3 脱敏导出（P3）

`GET /v1/export` 与 `siq-agent-security export [--out FILE]` 产出同一 JSON（`format=agentshield.export.v1`）：

- 含：公钥、enforcement_mode、资产摘要、准入 verdict/哈希/finding 规则、grant 状态与事实摘要、回执（seq/action/tool/reason/hash，**不含** `params` / `params_excerpt`）、`audit.jsonl` 尾部、回执链 `verify` 结果。
- **派生签名（DEV15-D）：** 写者对脱敏投影独立嵌入 `signing_schema=local_canonical/v1` + `signature`，并附 `derived_from`（`kind=agentshield.export.derived/v1`，`attestation_scope=share_projection_only`，可选 tip hash/seq）。此签只证明分享投影；**不得**把回执 `receipt_hash_chain` 或准入原文签名粘贴到导出上冒充仍“原样有效”。
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
   - 内存 session：容量上限 MaxSessions；满则拒绝新 session_id（禁止 LRU 清污点腾位，DEV16-A）
   - 空闲过期（DEV16-E）：仅无 taint 且无 trifecta 记忆的 session 可在 SessionIdleTTL 后释放；
     默认 30m；config `session_idle_ttl_seconds`：0=默认，-1=关闭，1..86400=秒。
     污点/trifecta session 永不过期腾位（避免同 ID 被当成干净会话）。
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
- `siq-agent-security verify [--chain local]`：逐行重算，报告首个 `seq` 不连续 / `prev_hash` 不匹配 / `hash` 不符 / `sig` 无效。
- **受管 checkpoint（DEV15-E）：** `<state>/checkpoints/<chain_id>.json`（`agentshield.checkpoint.v1`，`local_canonical/v1` 签名）保存最高 `seq`+`tip_hash`。路径必须在 `receipts/` **之外**；**禁止**把 `receipts/<id>/HEAD` 当锚点。Append 成功后由 serve 自动 Publish。有匹配 checkpoint 时 `history_integrity=verified`；截断/回滚相对该文件可检为 `failed`；无 checkpoint 时前缀有效仍为 `unknown`。诚实边界：同 UID 整 state 目录回滚不在本切片宣称；可用 `OpenCheckpointStoreAt` 指向独立挂载。

#### 3.8.4 fail-closed 表（适配器侧行为）

| 场景 | block | warn / audit_only |
| --- | --- | --- |
| API 不可达 / 超时 / 5xx | deny（reason 含「decision service unavailable」；写 `<state>/pending/decisions.jsonl` 行，`schema=pending_decision/v1`，`signed=false`，DEV07-C）。serve 启动与 `/v1/decide` 将未提升行补签为链上回执（`matched_rule_ids` 含 `pending.fail_closed`，DEV07-D；游标 `pending/promoted.lines`） | allow + stderr 警告 + 同 pending 行（outcome=allow）；同样可被 DEV07-D 补签 |
| 401 | deny | allow + 警告 |
| 返回非法 JSON | deny | allow |

### 3.9 `internal/openshell`（规格）

- 后端只用 CLI。显式环境变量与 Python `cli_backend.py` 相同：`SIQ_AS_OPENSHELL_CLI_BIN` 与 `SIQ_AS_OPENSHELL_GATEWAY_ENDPOINT`（必须成对）或 `SIQ_AS_OPENSHELL_ENV_SH`。`ENV_SH` 在 `source` 之后优先 `exec $SIQ_OPENSHELL_BIN`（research-engine `env.sh` 约定），否则 PATH 上的 `openshell`。
- siq-agent-security 额外发现 PATH 上的 `openshell`，走用户 CLI 配置（`HOME` / XDG / `OPENSHELL_*`），不注入 `--gateway-endpoint`。显式 `SIQ_AS_*` 优先于 PATH。Python 控制面后端不跟随此发现。
- `probe()`：`gateway info` 只表示调用了 OpenShell CLI（本地配置打印，端口上即使是 OpenClaw 也可能 rc=0）。必须以 `status`（或等价的会真正连网关的命令）做握手。`status` 出现 `InvalidContentType` / OpenClaw / Hermes 特征则 fail-closed。不按版本号假设能力。禁止猜测端口，禁止改别人的网关。
- **禁止** `openshell gateway start`。bootstrap、doctor、serve 都不启动网关。缺 CLI、网关没起、连错进程时 L0–L2 照常，并给出人类可执行修复。
- `siq-agent-security openshell doctor` 与 `GET /v1/openshell/doctor`：报告 CLI 路径、覆盖来源（`env_pair` / `env_sh` / `path` / `none`）、探针、身份、`human_next`；`started_gateway` 恒为 `false`。
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
- 所有写操作走 §3.8.1 端点并带**管理会话**；UI 无私钥。会话由配对进入内存，禁止 `localStorage` / 地址栏 `?token=`。`GET /ui-config.json` 不含凭据。

---

### 3.10.1 个人发现增量（2026-09-10）

按 [ADR-020](adr/0020-personal-discovery-and-skill-identity.md) 实施 UX-005：Skill 安装身份按本机规范化目录稳定生成，内容版本独立保留摘要；支持有界分类目录、profile Skills 和基于配置的多个消费者关系。新增关系仅为 inferred，不改变权限事实来源。台账兼容旧 locator/ID，路径与内容不变的迁移不撤权，内容变化保持原有复核与撤权语义。新个人扫描入口触发真实扫描并展示范围和结果；手动范围独立版本化保存，不能以缓存读取伪装重新扫描。接口和关系合同见 `packages/contracts/local-discovery.v1.schema.json`。

### 3.11 个人客户端 M1：启动识别与管理会话恢复（2026-09-10）

依据 [ADR-019](adr/0019-local-session-recovery.md) 和 [个人体验任务书](personal-experience-lan-team-development-taskbook-20260910-145507.md)。本节是当前已授权个人开发周期增量，历史发布/比赛快照不变。

- `GET /healthz` 为无 secret 的版本化服务识别响应；`status [--port N]` 严格校验产品和协议，不以 TCP 连通认定健康。
- 2026-09-12 UX-003/004 增量：`GET /healthz/instance` 使用独立 `local-service-instance-health/v1` 合同，附 `state_directory_id`。该值为 `sha256("local-state-directory/v1\0" + EvalSymlinks(Abs(state_dir)))` 的小写十六进制摘要；仅识别当前规范化目录，不是永久设备 ID、认证凭据或防同 UID 伪装证明。目录迁移改变摘要，符号链接别名复用同一摘要；不返回目录原文。服务启动时固定摘要，目录解析失败拒绝启动。`status`/`pair` 必须核对本地只读计算结果后才报告 ready 或发送恢复凭据；旧服务缺失新接口时明确要求升级，不回退为匹配。开发启动器只接受新合同。现有 `/healthz`、UI 会话与历史合同保持兼容。独立合同见 `packages/contracts/local-service-instance-health.v1.schema.json`。
- `/ui-config.json` 增加 `product`、`schema_version`、`session_recovery`、`pairing_available`，不返回 Cookie、token 或配对码。
- 新 UI 配对时提交 `remember:true` 与 `X-SIQ-Session:1`；access token 仍只在内存。HttpOnly/SameSite Strict/限定路径 Cookie 只用于 `POST /v1/session/restore`，有效期不超过原会话 12 小时，daemon 重启失效。
- `POST /v1/session/logout` 经现有 admin bearer 校验，注销该会话和对应恢复凭据；Cookie 不能直接调用其他管理接口。
- `<state>/admin-recovery.token` 是独立的本机恢复凭据，不提供给适配器；仅允许无浏览器 Origin/Fetch Metadata 的 `POST /v1/session/pairing`。该接口重发单次 5 分钟配对码、记录无 secret 审计，不返回通用管理会话、不更改 Grant。
- `pair [--port N]` 通过上述本机恢复路径生成新码，用户无需重启决策服务。该路径仍属 desktop-same-uid，不宣称能阻止恶意同 UID 进程。
- 会话相关响应 no-store，Host/Origin 检查、硬拒绝、单写者与回执语义不变。原文记录仍未开启。
- 本节响应和请求定义见 `packages/contracts/local-client-session.v1.schema.json`；既有客户端 `{code}` 配对方式保持兼容。

### 3.11.1 个人客户端初始化（2026-09-12，UX-003）

`init [--port N]` 复用当前状态目录和单写者锁，不启动服务、扫描资产、修改适配器或生成授权。成功输出 `local-client-initialization/v1`、`status:initialized`、实例 ID、目录摘要和实际配置端口，不能据此显示已保护。

- `config.json` 缺失时排他发布 block/optional/console 默认配置，默认端口 47611。显式 `--port` 仅供首次初始化；已有配置保持原字节，端口不一致拒绝，不能静默修改受管理适配器连接地址。
- `local-instance.json` 使用 `local-client-instance/v1` 与随机 256-bit 十六进制 `instance_id`，是当前本地安装的稳定标识，不是权限或团队注册身份。重复初始化、正常重启和迁移保留记录；复制目录会复制标识，未来团队注册不得直接把它当作可信唯一设备身份。缺失可在锁内创建，损坏/未知版本不得重建或覆盖。
- 配置与实例记录只接受有界普通文件（64 KiB），拒绝符号链接、目录、无效 JSON、null 和不支持版本。实例记录严格字段，已有配置允许保留额外设置。先验证两个现有文件再写缺失文件，复用同目录 fsync + 排他发布；中断后重试补齐缺失文件，不重置已发布配置/身份，也不删除残留或活跃锁。
- 写入必须持有真实 Writer（PID、nonce 和目录一致）；相同进程的并发调用也只能有一个 Writer。已有服务占锁时明确拒绝，操作者可先 `status` 检查。初始化不改旧状态/事实记录，不将历史未初始化状态自动升级为新写者兼容承诺。
- `serve` 对缺失配置先提示运行 `init`，不先产生密钥或凭据。已有配置仍可按原方式运行，稳定实例记录不是旧服务运行的强制迁移条件。开发启动器确认端口空闲后调用 `init --port N`，成功才启动；端口已被匹配实例使用时直接复用，不触发初始化写入。
- 合同见 `packages/contracts/local-client-initialization.v1.schema.json`。本增量不等于二进制来源校验、安装包分发、系统后台注册或跨 OS 原生验收完成。

### 3.11.2 原生单命令启动（UX-003）

`start [--port N]` 在同一 Go 二进制内组合初始化和前台服务运行，无 Python 依赖。省略端口时沿用配置或默认 47611；显式端口与已有配置冲突拒绝。先只读验证配置与端口：匹配 `/healthz/instance` 时输出原健康合同并退出，不换配对码、不改文件；其他服务或不兼容响应占用端口时拒绝，不初始化或终止进程。端口空闲时调用既有 `init` 和 `serve`；预检不能消除竞争，最终仍由 writer 锁和 listen 排他判定，竞争失败不删除锁、不杀进程。

新启动保持前台运行，关闭终端可能停止服务；该命令不声明后台注册或注销保活。操作者在新终端用 `pair` 恢复配对。首版不提供 mode 覆盖、浏览器自动打开或 stop，避免复用已有服务时静默忽略配置变更。系统后台机制将在独立增量中接入。

### 3.11.3 停止时的请求排空与写锁（UX-003）

前台及后续系统服务的停止使用同一语义：收到停止信号后停止接受新业务请求，在途 HTTP handler 完成之前不返回 serve、不释放状态 Writer。默认给予 HTTP 连接 3 秒正常排空时间，超时后关闭连接以取消请求上下文；仍须等待已经进入的 handler 结束，不能以连接关闭推导磁盘事务已结束。忽略取消的操作可能延长退出，不能为满足停止时间而提前解除写锁。晚到请求返回 503，不进入原处理器。正常退出撤销 signal 注册，异常监听退出同样排空在途 handler。外部系统强杀仍按原状态恢复合同处理，不能宣称优雅退出。

### 3.11.4 Linux 用户服务配置导出（UX-003）

`service-unit` 只读已初始化状态和当前二进制位置，输出 systemd 用户服务配置。执行路径和状态目录固定为规范化绝对路径，拒绝控制字符；二进制路径中的 `$` 在首版明确拒绝，避免 systemd 命令替换歧义；`%` 按 systemd 规则转义。配置使用 `serve`，不能用会复用其他进程后退出的 `start` 作为服务主进程。用户先显式 init；缺失或损坏实例/配置时不输出配置。

服务以当前用户运行，不 sudo、不写系统目录；默认不自动重启，以免永久配置错误形成循环。SIGTERM 停止，30 秒后系统可强杀，强杀不能记为优雅排空。stdout/stderr 为 null，避免 serve 的一次性配对码进入 journal；管理配对另行使用 `pair`。配置包含 UMask=0077。本命令不执行 systemctl 或注册开机启动，不声称安装完成；后续自动安装事务须校验文件归属、处理重载失败和卸载恢复。其他 OS 明确拒绝使用 Linux 导出命令，不能以交叉构建推定支持。

M40 原生验证增量：systemd 255 实际拒绝含双引号的可执行文件路径；导出现在提前拒绝二进制路径中的双引号和反斜杠，连同美元符号给出可操作错误。空格/百分号二进制路径以及含美元符号/百分号/双引号的状态目录已通过真实运行验证。此限制只约束导出的可执行路径，不把允许状态目录的转义误作非法可执行路径支持。

### 3.11.5 用户服务配置发布记录（UX-003）

后台安装先在状态目录发布签名配置记录，再排他发布对应单元文件。记录绑定 local instance、目录摘要和完整 unit SHA-256；重试必须通过签名与全部绑定校验，配置变化要求新的迁移流程，不能覆盖旧记录。首次发布前目标已存在则拒绝，即使字节相同也不接管；已持有签名记录时可补发缺失单元，存在但内容改变拒绝。沿用 state Writer 与同目录原子发布，不删除未知文件。记录表达配置发布意图，不表示系统服务已注册、运行或权限已生效。此为后续 systemctl 注册/失败恢复的持久前置条件，不直接执行系统命令。

### 3.11.6 Linux 用户服务注册（UX-003）

`service-register [--runtime]` 在当前用户 systemd 中注册已归属配置；默认持久 link，`--runtime` 仅当前登录管理器生命周期。命令本身不启动服务或启用登录自启。沿用 §3.11.5 准备和 Writer，注册期间保持锁；只调用无 shell 的 `systemctl --user`，不使用 force/sudo。每次外部调用有超时和输出上限，错误不回显系统原始输出。

注册前读回 LoadState、FragmentPath、DropInPaths、UnitFileState：缺失可 link；已有单位必须 loaded、无 drop-in、规范化 FragmentPath 指向本实例已验证文件，且 linked/linked-runtime 与本次范围相同，否则拒绝。link 后 daemon-reload，再复验上述字段才返回成功。中断或 reload 失败保留配置和链接，不报告成功；重试再次核对归属并 reload。不删除未知链接、未知 drop-in 或失败时盲目回滚。当前不提供范围变更、升级或卸载，独立后续事务处理。

CLI 成功以人类可读文本报告“已注册、尚未启动”；签名配置记录保持原意图语义，不新增运行状态字段。真实 manager 读回与文件归属用于防误操作，不抵抗恶意同 UID 竞争。

### 3.11.7 Linux 用户服务启停与状态（UX-003）

`service-status` 只读核验已存在签名身份、配置归属、manager 来源与状态；不创建密钥/目录或补发文件。`service-start` 核验后请求 manager 启动，只有 active、正数 MainPID 与本目录健康检查共同通过才报告就绪。`service-stop --confirm-stop` 为显式停止确认；未带确认不修改任何状态，提示 block 模式下智能体后续操作将被拒绝。停止后须读回 inactive、MainPID=0、Result=success 且 serve.lock 已消失才报告正常停止；超时/强杀/锁残留均报不完整，不删除锁或杀未知 PID。

运行时不获取 daemon 的主 Writer；服务管理变更共用状态子目录 `service-control/` 的既有 Writer 格式，串行化 prepare/register/start/stop。状态查询只读；此锁不修改授权与台账。登记与启停均核验签名配置和无 drop-in 的 manager 来源，未知配置失败关闭。现有签名身份以只读加载方式读取，缺失不生成。三 OS 通用加载器仍保留已有环境种子优先语义。

### 3.11.8 Linux 服务注销（UX-003）

`service-unregister --confirm-unregister` 仅移除当前实例的系统注册链接，保留状态配置、签名记录、密钥、授权和历史。运行中拒绝，用户先显式确认停止。获取生命周期锁及主 Writer，核验已存在签名配置；manager 必须 inactive/MainPID=0/Result=success、无 drop-in、linked 范围、FragmentPath 对应同名单元链接且规范化目标为本实例文件。仅删除该符号链接，不使用会扩散移除其他链接的 disable，不删除普通文件或未知用户对象。该服务链接写入例外与注册同属本轮授权生命周期范围。

删除后 daemon-reload，读回 not-found、空 FragmentPath/DropInPaths/UnitFileState、inactive/MainPID=0 才报告注销；失败不清理状态记录。删除成功但 reload 前中断时，重试仅在已停止且 FragmentPath 已缺失的条件下 reload 后复验，不假装删除其他文件。已注销可重复确认，未曾注册的有效准备实例也报告“当前未注册”。注销不等于程序或数据卸载，数据删除是独立显式操作。

### 3.11.9 原生客户端制品暂存（UX-003/014）

`client-stage --manifest FILE --binary FILE` 复用既有 skill-manifest/v1 的内置发行根验签，不接受候选提供的信任根或 CLI 跳过验签。严格解码、清单上限 1 MiB；要求 manifest_version=1、正确产品名/非空版本、当前 GOOS/GOARCH 唯一制品、有效 SHA-256 与大小 1–128 MiB。候选必须普通文件，不执行；按已签名字节数限流复制并校验摘要，再发布到状态目录 `client-releases/<binary-sha256>/siq-agent-security[.exe]`（0700）和 `manifest-<manifest-sha256>.json`（0600）。目录 0700，仅采用同目录暂存/排他硬链接发布，不替换既有对象。

暂存不获取 daemon 主 Writer，使用独立 `client-releases` 子目录既有 Writer 格式，允许运行中准备候选；不改 config/unit/签名身份/授权，不下载或启动候选，不停止服务。签名验证必须发生在创建状态之前。重试复核已存在普通文件内容，缺失对象可补齐；漂移、symlink、大小/哈希冲突均拒绝，不覆盖。磁盘不足/发布失败保留可复验独立对象，不报告升级完成。清单仅作为候选来源证明，不代表版本兼容、OS 代码签名或真实平台支持；升级切换还需单独状态兼容与停止/恢复协议。

### 3.11.10 签名客户端兼容声明与升级预检（UX-003/014）

新增独立 `skill-manifest.v2`，保留 v1 字节/签名/合同。v2 必须签入 client_compatibility：state_profile=`agentshield-local-ledger/v1`（本项目现有本地台账格式族，含已实施个人状态对象）、service_protocol=`local-service-instance-health/v1`、migration=`none`。本实现只接受该精确组合，不自动迁移状态。每项 binary artifact 的 bytes 必须为正数且不超过 128 MiB。发行者声明兼容不替代目标真实集成验收，也不证明旧任意二进制会拒绝未来格式。

`release-manifest --client-compatible` 显式产生 v2，否则仍 v1；该参数只能用于已验证保持现有状态格式的候选。旧 Skill bootstrap 继续使用旧 v1，不擅自重签冻结制品或假装支持 v2。新增原生 `client-upgrade-check --manifest FILE --binary FILE`：只读验证发行签名、唯一当前平台 pin、候选大小/摘要和上述精确兼容声明，不执行候选、不创建状态、不停止/切换服务。旧 v1 可暂存但升级预检明确拒绝。通过仅意味着来源/完整性/声明预检通过，切换前还需重新校验及独立事务；不将它作为旧写者隔离或升级成功证明。

### 3.11.11 服务配置成对切换事务（UX-003/014）

服务配置与签名归属记录切换采用 `local-service-switch/v1` 本地签名日志，保存 source/target 记录和 unit 字节，全部绑定当前实例/目录/同一 unit 名与各自 SHA-256。日志只允许 Writer 持有者准备，候选发行验签与 manager 停止是上层切换命令的前置条件；底层不执行 systemctl、不选择或启动候选。

先排他发布 `service-switches/<日志sha256>.json`，再发布 `service-switch.pending.json`（相同签名字节）。任何不一致的 pending 拒绝；未完成时本版本 serve 拒绝启动。应用前验证当前两文件分别等于 source 或 target，未知字节或缺失拒绝；再分别以同目录已 fsync 临时文件替换仅已验证旧内容，重试只完成未达 target 的文件。完成后排他发布同内容 `.done.json`，再核对并移除 pending。日志/旧版本材料保留，配置和其他台账不回滚。

恢复重新验签和绑定后前滚到同一 target；不得通过恢复重签新目标或覆盖未知对象。此事务只完成配置文件切换，不代表 manager reload/启动/健康通过；上层尚需对应阶段恢复。强制停止旧任意版本不在该标记保证内，主 Writer 仍是防混跑前提。无需迁移状态的发行候选仍需上层逐次复验。

## 4. 平台适配器规格

### 4.1 OpenClaw（P0）

**安装门禁（L1）**：`~/.openclaw/openclaw.json`

```json5
security: { installPolicy: { enabled: true, targets: ["skill","plugin"],
  exec: { source: "exec", command: "<abs path>/siq-agent-security", args: ["policy-exec","--json"],
          timeoutMs: 10000, trustedDirs: ["<dir>"] } } }
```

`siq-agent-security policy-exec`：stdin 读 OpenClaw 请求（含 staged 路径与 `skill.installSpec`）→ 对 staged 目录跑 §3.6 → 输出 `{"decision":"allow|warn|block","reason":...}`：quarantine → block；admit_with_conditions → warn（附「安装后请 grant」）；admit → allow。任何内部错误 → block（OpenClaw 自身在 exec 失败时也 fail-closed）。

**运行时（L2）**：插件 `adapters/runtime/openclaw-agentshield/`（TypeScript，`definePluginEntry`）：

- 安装资产包含 `openclaw.plugin.json`（插件 ID、无凭据配置 schema）和 package 的 `openclaw.extensions` 入口。安装器把插件绝对目录加入 `plugins.load.paths`，启用本插件 entry；已有 allow 列表时仅追加本插件，保留其他插件。显式全局禁用或 deny 本插件、配置类型错误时安装拒绝，不擅自打开全局插件开关。卸载只移除本插件的路径/entry/allow 项。
- 插件配置目录优先采用 `OPENCLAW_STATE_DIR`，否则使用 `~/.openclaw`；用于原生平台隔离实例，不能通过环境覆盖冒充 OS 隔离。

- `before_tool_call`（priority 10）：POST `/v1/decide`；映射 `deny → {block:true, blockReason}`、`hold → {requireApproval:{title, description, severity:"warning", timeoutMs}}`、`redact → {params}`、`allow → undefined`。
- `after_tool_call`：POST `/v1/observe`（结果截断 64 KiB 后发送，服务端再脱敏）。
- 超时：插件侧 5 s；OpenClaw 钩子 15 s fail-closed 兜底。
- 配置：`~/.openclaw/siq-agent-security.json` 保存 `endpoint`、`token_path`、`enforcement_mode`。

**卸载**：`siq-agent-security adapter uninstall openclaw` 删除插件目录并把 `openclaw.json` 恢复到 `<state>/backups/` 中的副本。
- **安装首备（DEV07-A）：** 改写已有用户配置前，以 `*.siq-agent-security.orig`（O_EXCL、0600）保存首次见到的原文；重装不得覆盖。坏 JSON、指向配置的 symlink、未知 `enforcement_mode` 拒绝且不改写。配置写入同目录暂存+Rename。
- **外科卸载（DEV07-B）：** OpenClaw/CodeBuddy 在活配置上剥离本产品 `installPolicy`/hooks，保留安装后用户字段；冲突（坏 JSON 等）返回 `RecoveryPlan`，不静默整文件回滚。首备仅供人工恢复参考。
- OpenClaw 重装记录保留先前由本产品创建的插件目录/文件及本产品配置的归属；损坏的既有安装记录拒绝继续。卸载同时移除本插件运行时注册，不把“安装资产存在”当作原生运行时已验收。

### 4.2 Hermes（P0）

**运行时（L2）**：`~/.hermes/plugins/siq-agent-security/`（`plugin.yaml` + `__init__.py`，纯 stdlib `urllib`）：

- `register(ctx)`：`ctx.register_hook("pre_tool_call", cb)`、`ctx.register_hook("post_tool_call", cb)`。
- `pre_tool_call(tool_name, args, task_id, session_id, tool_call_id)` → POST `/v1/decide` → `deny/hold` 返回 `{"action":"block","message": reason}`（Hermes 无 approval 通道：hold 在 Hermes 上退化为 block 并在 message 里给控制台 URL）；`allow` 返回 `None`。
- `post_tool_call` → `/v1/observe`。
- 插件不修改 Hermes 核心（AGENTS.md 规则）。

**安装门禁（L1，弱）**：`siq-agent-security adapter install hermes` 生成 `~/.local/bin/hermes-skills-install` 包装脚本：先 `siq-agent-security admit <src>`，非 quarantine 才调用真实 `hermes skills install`；SKILL.md 引导用户用包装脚本。本地放入 `~/.hermes/skills` 由 inventory 周期扫描（`serve` 每 5 分钟）发现未准入 Skill 并在 UI 标红。

**工具边界（grant 输出）**：写 `platform_toolset_modes` allowlist（Hermes siq-patches 支持闭世界模式）；写前备份。

### 4.3 CodeBuddy / WorkBuddy（P1）

**配置目录（2026-09-07 增量）**：安装、状态、自动发现与卸载统一读取进程环境 `CODEBUDDY_CONFIG_DIR`，未设置或为空时保留 `~/.codebuddy`。覆盖值须为绝对路径，现存路径及祖先不得为符号链接；非法覆盖明确拒绝操作，自动发现忽略该平台，不静默回退默认目录。CLI 与管理 API 使用相同解析逻辑；管理 API 不接受请求正文指定配置目录。卸载须核对最新安装记录中的目标路径，环境改变导致记录与当前配置目录不符时拒绝，避免误删另一实例的钩子。多实例建议分别使用独立 SIQ 状态目录；本增量不扩展 inventory 的扫描范围。

**钩子启动失败（2026-09-07 增量）**：CodeBuddy 将普通非零退出视为非阻断错误，不能用进程退出码 1 代替 pre hook 的拒绝。状态目录、完整配置或 decision token 读取失败时，钩子仍读取事件并输出结构化 PreToolUse 结果；无有效完整配置时按 block，已验证 warn/audit_only 配置但 token 不可用时按 advisory allow。PostToolUse 在客户端不可用时只返回非阻断结果，不制造 observation。状态目录可用时沿用 pending 记录；目录不可用时拒绝仍生效，但不声称已持久化。返回原因仅使用固定类别，不含底层路径、配置内容或凭据。此机制不覆盖二进制未启动、被杀、超时或 stdout 管道不可写的宿主行为。

**运行时（L2）**：`~/.codebuddy/settings.json` 追加（需用户确认，幂等）：

```json
{"hooks":{"PreToolUse":[{"matcher":".*","hooks":[{"type":"command","command":"<abs>/siq-agent-security hook codebuddy","timeout":5}]}],
          "PostToolUse":[{"matcher":".*","hooks":[{"type":"command","command":"<abs>/siq-agent-security hook codebuddy --observe","timeout":5}]}]}}
```

`siq-agent-security hook codebuddy`：stdin 读 `{session_id, tool_name, tool_input, cwd, permission_mode}` → `/v1/decide` → stdout：

```json
{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"allow|deny|ask","permissionDecisionReason":"..."}}
```

`hold → ask`、`deny → deny`、`redact` → 当前适配器尚未接入原生改参，退化为 `ask`。

不使用 Skill frontmatter hooks（仅 fork Skill 且默认关闭）。

### 4.4 Trae / TraeWork（P2，审计）

无钩子。SKILL.md 引导：安装前 `siq-agent-security admit`；`serve` 周期扫描 `.trae/skills`；UI 标「审计模式，无法阻断」。`skill-manifest.support_matrix` 对应行 `status=audit_only, tiers=[L0]`。

### 4.5 适配器公共约定

- 只做 HTTP + 映射，不含任何判定逻辑、不含规则、不含密钥。
- 每个适配器附 `adapters/runtime/<x>/README.md`：安装、卸载、fail-closed 行为、已知限制。
- E2E 用例：装 → 扫 → 授 → 越权被拒，一条录屏 + 一份回执文件。

---

## 5. SKILL.md 与发布

### 5.1 `skills/siq-agent-security/`

```
SKILL.md                 frontmatter: name siq-agent-security, description ≤60 字符句号结尾,
                         allowed-tools（声明本 Skill 自身需要：terminal/read_file）, compatibility
scripts/bootstrap.sh     POSIX：定位/下载二进制 → 校验 manifest 签名与 sha256 → serve → 打印 UI URL
scripts/bootstrap.ps1    Windows 同上
scripts/adapter.sh       调用 siq-agent-security adapter install <platform>（探测当前平台）
references/tiers.md      档位说明与各平台限制（给模型读，减少幻觉）
references/decision-table.md  §3.6.4 的精简版
evals/evals.json         SkillEvaluator 格式：装恶意 Skill 应 quarantine、官方 Skill 应 admit_with_conditions、越权应 deny
skill-card.md            本 Skill 自己的卡
skill-manifest.json      发布时生成并签名（schema: skill-manifest）
```

SKILL.md 正文结构：`# siq-agent-security Skill` / 简介 / When to Use / Prerequisites / How to Run（三步：bootstrap → adapter → 打开 UI）/ Quick Reference（子命令）/ Procedure（四个子 Skill 的调用顺序与「结果由二进制给出，不要自行判断」）/ Pitfalls（无钩子平台、fs 不热更新、Windows L3）/ Verification。

**模型行为约束写法**：正文明确「你（模型）不判断 Skill 是否安全；运行 `siq-agent-security admit` 并原样呈现 verdict 与 Skill Card」。

### 5.2 发布流程（CI）

1. `go test ./...`、`go vet`、`gofmt`；Python 全量测试。
2. 交叉编译 `linux/{amd64,arm64}`、`darwin/arm64`、`windows/amd64`，`-ldflags "-X main.Version=<tag>"`，产出 sha256。
3. 计算 `skills/siq-agent-security/` `content_hash`；生成 `skill-manifest.json`；用发布密钥（环境变量 `SIQ_AGENT_SECURITY_RELEASE_SEED`）签名；bootstrap 脚本内置发布公钥。
   Go `manifest-verify` 同样只接受内置信任的发行公钥，清单 `signed_by` 不授予信任。开发签后自检可显式提供调用者已知的公钥，但不等同于发行者验证通过，不放宽默认 CLI。
4. 打 `siq-agent-security-skill-<tag>.zip`（Skill 目录 + manifest）供 TraeWork 上传 / ClawHub / 手动安装；GitHub Release 挂二进制。
5. 自扫描：CI 用刚构建的二进制对 `skills/siq-agent-security/` 跑 `admit`，必须为 `admit_with_conditions`（声明 terminal/network），不得 quarantine。

操作清单（tag 未切前 URL 对象不存在；bootstrap 不下载）：[`agentshield-release-checklist-v1.md`](./agentshield-release-checklist-v1.md)。哈希核对脚本 `scripts/agentshield-release-check.sh` 不需要种子；重签需要 `SIQ_AGENT_SECURITY_RELEASE_SEED`。矩阵不得出现 `supported` 行。

### 5.3 分发仓库

不新开（ADR-011 D5）。若市场要求根目录即 Skill，由 CI 镜像 `skills/siq-agent-security/` 到分发仓，源码不迁出。

---

## 6. 安全模型（siq-agent-security 自身）

| 威胁 | 缓解 | 残余 |
| --- | --- | --- |
| 恶意 Skill 冒充 siq-agent-security 引导用户跑假二进制 | manifest 签名 + sha256 内置于 bootstrap；UI 显示公钥指纹 | 用户跳过校验 |
| 模型被注入后调用 `grant --approve` | CLI 批准需 `--approve-as` 且写 `channel`；UI 批准需管理会话；SKILL.md 禁止模型批准 | 同 UID 模型仍可执行 CLI 或读状态目录 —— desktop-same-uid 只记录人工声明，不构成隔离 |
| 决策 API 被本机其他进程调用 | loopback + Host 允许列表 + 决策/管理分权 | 同用户下其他进程可读 token 文件（OS 边界）；管理会话不经 ui-config 泄漏 |
| 适配器被绕过（Agent 用原生 HTTP 出网） | OpenShell 网络 default-deny（L3）；无 L3 时 UI 明示「仅工具层拦截」 | Mac/Win 无 Docker |
| 回执被改写 | 只追加 + 哈希链 + 签名；`verify` | 私钥泄露（状态目录被读）|
| 规则包被替换 | 外部包验签 + 防降级；内嵌包为基线 | 二进制本身被替换（由 manifest 校验覆盖）|
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
skills/siq-agent-security/
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
# UI（siq-agent-security 本地控制台；企业控制台仍是 npm run build）
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
| W5 Skill 包 | SKILL.md、bootstrap、evals、manifest、release | **完成**（Skill 目录、evals、bootstrap 验签、`grant` CLI、自扫描不得 quarantine、已签名 `skill-manifest.json` + 四目标哈希。GitHub Release `siq-agent-security-v0.2.0` 已挂二进制；bootstrap 仍不下载。矩阵仍无 `supported` 行） |
| W6 材料 | README、演示、基线更新、十日谈 | **完成**：评委入口 `AGENTSHIELD.md` + 演示步骤；2026-09-05 Spark linux 证据已归档：Hermes 实机插件、OpenClaw `policy-exec`、CodeBuddy `hook`（隔离 HOME）。矩阵备注已对齐证据，**仍无 `supported` 行**。Release tag 已切（清单 [`agentshield-release-checklist-v1.md`](./agentshield-release-checklist-v1.md)）。L3 可选：须验明正身的 OpenShell |
| W7 本地台账 | 企业治理语义在本地文件态落地（资产/五态权限/风险/漂移/导出）；Control API 仍非现场依赖 | **P0–P3 已落地**（§2.4 / §3.5 / §3.8.1 / §3.10）：assets 状态机、profiles/agents.list、五域补丁、漂移、exec 无 host deny、findings 接受、audit.jsonl、脱敏导出、`sync --control-api`（默认不跑）、可选 `--connectors-dir`、MCP 配置原生只读（`mcp_server`）。矩阵仍无 `supported` 行 |

---

## 10. 开放问题

1. **AST 层**：tree-sitter（cgo，破坏纯 stdlib 与交叉编译便利）vs 纯 Go 词法（只识别 `os.system(`、`shell=True`、`ctypes.` 模式，接近正则）。倾向后者作为 v1.1，正式 AST 留控制面。
2. **`candidate.source_type` 增 `skill_dir`**：合同升版（v1 → 追加 enum 属非破坏，但需同步 Edge/Web types）。
3. **Hermes hold 语义**：无 approval 通道，退化为 block + URL；是否值得给 Hermes 提一个 `pre_tool_call` 返回 `ask` 的上游 PR。
4. **StepFun 云端路由**：`model_routing` 在 OpenShell 走 `inference.local`，脱敏 broker 是否复用 research-engine 的 provider 合同（只读参考，不依赖）。
5. **训练营 9/20 工具包**：若 NVIDIA 发布 OMS 签名工具链，`skill-manifest.signed_by` 是否切换到证书链（当前 Ed25519 本地信任根）。

## 10. Trusted Intent Authority V2 增量（2026-09-07）

本节承接用户提供的 Trusted Intent Authority & Action Binding V2，优先于第一版客户端 Intent 语义。
`intent-contract.v2.schema.json` 为受信签发格式，v1 合同保留供历史读取，不允许运行时 inline 签发。

- `POST/GET /v1/intents`、`GET /v1/intents/{id}` 和对应 `/v1/intent-bindings` 端点只接受管理会话（capAdmin）；Decision token 一律 403。
- 管理面提交结构化 V2 合同，服务端校验身份、时间窗、工具/effect、受限 JSON Pointer 与资源操作符后计算 digest 并签名。调用方提供的 digest/signature 不作为可信输入。
- `intents/<id>.json` 与 `intent-bindings/<id>.json` 通过同目录临时文件 fsync 后排他发布；签名文件同时是签发/绑定的不可变审计记录，发布失败不激活授权。ID 不得覆盖；绑定从已验签 Store 读回合同，不接受外部 Contract 充当 authority。
- 会话绑定按 platform/session/agent 唯一且只追加；冲突绑定拒绝。过期绑定保留并导致拒绝，重启后也不得退回 optional Grant-only。暂不提供任务切换/撤销入口，避免隐式解绑。
- 参数使用 RFC 6901 指针（含嵌套对象、数组和 ~0/~1 转义），支持 equals/one_of/prefix/suffix/regex；正则至多 1024 字节，使用 Go RE2。未知操作符、缺失路径和不匹配全部拒绝。
- filesystem 资源使用绝对 POSIX clean 路径与目录边界匹配；network 使用 URL host、小写和移除末尾点，非 ASCII host 拒绝（管理员须预先输入 ASCII/Punycode）；message 使用显式 recipient。无法确定资源的工具失败关闭，不用 shell 文本猜测资源。符号链接仍由文件安全层处理。
- evidence_ids 的 `external:https://…` 表示明确的外部引用而非已核验证据；本地 evidence ID 必须在状态目录 evidence 中存在且格式一致。
- `intent_enforcement=optional|required` 独立于运行时 enforcement_mode；新回执记录 bound/unbound。V2 授权由 intent 包确定性执行，receipt 只消费已解析合同。
- desktop-same-uid 仍无法隔离恶意同 UID 进程；此轮建立协议授权完整性，不宣称 OS 隔离。

### 10.1 Decision → Observe 关联

新回执增加 `record_type`、`decision_receipt_id`、`parent_action_id`、`task_seq`（均为可选扩展，不重签历史回执）。服务端将单次决策链序号纳入 action ID；同一 task/session 的 task_seq 单调增加，parent 指向上一条允许或 redact 的动作。
Observe 显式携带 action_id 与 decision_receipt_id；旧适配器可用相同 platform/session/agent/tool/tool_call_id 唯一定位。缺 tool_call_id 时必须携带相同参数，若有多个候选则拒绝，不能猜测。
只有 allow/redact 或已由本地管理面批准的 hold 可观测。同一动作相同结果摘要幂等返回原回执，不同摘要返回 409。结果超过 64 KiB 拒绝，避免截断掩盖冲突。
关联状态从签名回执恢复，内存最多 8192 项，默认 24h 窗口；溢出拒绝新决策，过期动作不再接受 Observe。过期仅清理动作关联，不清理 bound/tainted 会话安全状态。

24h 窗口从签名 decision 的 `issued_at`（当前秒精度）计算，到达边界即拒绝；内存运行期与重启恢复使用相同精度。较晚的 observation 不延长原动作窗口，也不使 bound/tainted 会话变回 clean。

### 10.2 V2 完整性补齐（2026-09-07）

执行前 hold 检查：`POST /v1/hold-status` 使用 capDecision，只读，不接受批准字段。请求严格限定 platform/session_id/agent_id/tool/tool_call_id/action_id/decision_receipt_id/params，必须提供完整服务端动作身份和原参数。返回合同 `hold-status/v1`：status 为 pending/approved/denied/expired/consumed，带原 action_id、decision_receipt_id、expires_at 和 reason_code；不返回参数或管理身份。身份/参数不匹配、未知动作或非 hold 返回 400，匿名返回 401。状态由已有签名 decision/resolution/observation 恢复，不新增授权记录；查询不续期。原 hold 到期（含边界）、已观察或当前授权不再匹配时不得报告 approved。

OpenClaw hold 按顺序执行：先等待上述本地批准，再返回原生 requireApproval。默认本地等待上限 10 秒（配置 holdWaitMs，范围 100–10000ms），每次 HTTP 仍受 timeoutMs 与总剩余等待时间限制；上限为适配原生 15 秒 hook 预算而设，不能把等待挂起为无限期。管理端需在等待期间处理当前 hold，超时后该次调用阻断，迟到批准不会自动重新执行。平台审批超时不超过原 hold 剩余有效期；本地拒绝、异常响应、断连和取消均在 block 下阻断。warn/audit_only 仍由服务端产生 allow/advisory，不把该模式升级成强制阻断。本地状态查询是执行前检查快照，不是外部工具执行完成证明；平台等待期间的外部状态变化仍须单独验证。

- Shell/exec 命令不作完整解释或执行。所有文本命令均带 `process.exec` 和 `unknown`；可识别的网络词仅追加 `network.request`，不能证明没有其他副作用。V2 Intent 遇到 unknown 拒绝（即使 allowed_effects 包含 unknown），optional 无绑定保留原 Grant 语义。
- 结构化 file/network/message 工具使用统一的内存 Resource 类型做提取/归一化/匹配；`resource_refs` 只存 domain 与归一化资源的 canonical SHA-256，参数、URL query、文件路径和收件人原文不增加到签名资源字段。无法提取时为空，不伪装已观察到资源。
- 新回执可选 `principal` 来自已验签 Intent；`provenance_refs` 仅为管理面签名的保留引用（最多 64 个合法 ID），不解释传播图、不参与扩大权限，Decision 自报不成为可信引用。Envelope、Intent V2 和 Receipt 增加兼容可选字段；原 resources 留作历史字段，新生产者只生成 typed resource_refs。
- unbound 首次进入可信任务时重置任务序号/父动作，不清除 taint/trifecta。旧任务延迟 Observe 仍传播污点，但不改当前任务序号/父动作；旧任务 hold 批准亦不成为当前任务父动作。重启回放遵循同一规则。
- 参数比较中 JSON 数值按精确数值比较（1 与 1.0 相等，不转换为 float64）；资源 equals/one_of 与正向前缀在两侧应用相同归一化。正则在归一化输入上按 Go RE2 执行，表达式本身不做路径清理。

性能测量入口 `perfbaseline -intent` 保留默认单绑定 / 200 样本，可用 `-intent-bindings`（1–4096）与 `-intent-samples`（1–10000）复测不同规模；报告同时记录命中 / 缺失绑定查找和约束匹配的 p50/p95/p99，不包括 HTTP、回执 fsync 或真实工具执行。

绑定查询使用既有 `sha256([platform, session_id, agent_id])` 确定性 ID 直接读取不可变签名文件；每次请求仍验证目标绑定和 Intent，不引入权限缓存。管理列表仍检查整个目录的记录完整性和容量。无关绑定损坏由管理枚举发现，不再阻塞其他会话的有效授权；目标绑定损坏/签名异常/过期始终拒绝，已绑定会话缺失记录仍由 receipt 的粘性状态拒绝降级。

JSON 数值匹配的单个数字词法表示上限为 1024 字符，超过上限按不匹配处理；十进制等价比较不改变既有 canonical/signing 的序列化规则。

### 审批后执行检查点候选（2026-09-07，未进入默认安装）

当前 OpenClaw 本地 hold 预检与平台批准之间存在可复现的 Grant 撤销窗口。候选通过配套宿主扩展 `requireApproval.beforeExecute(finalParams, signal)` 在平台允许后等待适配器重新校验；宿主仅接受严格 true，异常、拒绝、取消和五秒预算超限均 veto，适配器以一秒预算查询现有强关联 hold-status。此项不是官方 API 或默认产品已支持合同，只在固定源指纹的临时副本验证；仅改一侧不生效。当前八场景覆盖与未覆盖故障见 [撤销验收报告](trusted-intent-v2-approval-revocation-20260907-220037.md)。检查点不构成与外部副作用原子提交的租约。

候选检查点增量（2026-09-07 22:08）：[原生故障验收](trusted-intent-v2-checkpoint-faults-20260907-220834.md) 已覆盖正常批准、同步异常、Promise 拒绝、undefined/真值字符串、五秒预算、取消后返回 true、最终参数改写和审批后失联。最终参数不匹配由真实 hold-status 返回 400，只有正常对照产生执行及 observation。此增量不改变候选未进入默认安装的状态。

### 宿主检查点能力识别与适配器集成（2026-09-07）

适配器的 hold 路径要求本次原生 hook context 提供整数 `approvalExecutionRecheckVersion: 1`，表示宿主在平台批准后等待 `requireApproval.beforeExecute(finalParams, signal)` 并执行严格 true/异常/取消/超时否决。该值由配套宿主执行包装器生成，不能从工具参数、事件、自定义插件配置或环境变量读取。缺失、未知版本、字符串或布尔值均视为不支持；block 模式明确阻断当前 hold，不能回退到已知存在撤销窗口的旧审批路径。allow/deny/redact 的既有映射保留；warn/audit 的失效处理仍按原模式表执行。

当前适配器及内嵌安装资产应携带实际 `beforeExecute` 回调，在一秒预算内用原动作身份与最终参数重新查询 hold-status，仅仍 approved 且未取消时返回 true。配套宿主补丁 v2 增加上述 context 能力标记，原版和旧候选 v1 不具备该标记。协议标记属于同一受信宿主执行边界，不是对恶意同进程插件的密码证明。原版升级适配器后，hold 需要配套宿主支持才能完成；不得把这种明确的兼容性要求写成无缝兼容。

宿主兼容工具提供 `inspect/apply/restore`，只支持固定包版本和源码指纹。修改操作要求显式指定运行时与独立备份目录，先持有 POSIX 文件锁、持久化原始字节和恢复记录，再同目录原子替换目标；保留原文件权限和属主。恢复只接受已记录的目标身份及预期补丁后字节，拒绝覆盖后续改动。记录与完成标记只新建，不原地覆盖；替换后但完成标记前中断可通过相同命令幂等收尾。工具不更新用户配置、插件或自动重启服务；磁盘文件状态不代表运行进程已加载新代码。Windows 修改路径暂不支持，不能绕过文件锁运行。

### Trusted Intent V2：绑定撤销（原始要求 §42）

管理面新增 `POST /v1/intent-bindings/{binding_id}/revoke`，请求仅含 `expected_intent_digest`（64 位小写 SHA-256），成功返回 200 的签名 `intent-binding-revocation/v1`。相同绑定和 digest 的重复撤销返回首次原记录；digest 不匹配返回 409。Decision credential 无权操作。`GET /v1/intent-bindings/{binding_id}/revocation` 读取签名撤销记录，未撤销为 404；原绑定 GET 保留不可变历史。

撤销是终止该运行时身份的授权，不是删除绑定或回退 unbound。新增 `<state>/intent-binding-revocations/{binding_id}.json`，含原完整签名 Binding 的 canonical SHA-256、撤销时间、固定 reason_code、signing_schema 与签名。记录由既有 signing/key 签发，只新建，不修改原 Binding/Intent；本身构成受信管理面的撤销审计。只有现存签名绑定可撤销，数量受绑定容量 4096 限制，读取为确定性路径，无 TTL 清除。

运行时每次可信绑定解析读取并验签撤销记录。存在有效撤销时返回 `intent_binding_revoked`；撤销记录损坏、非普通文件或绑定摘要不匹配时失败关闭。即使旧绑定文件被移除，保留的有效撤销记录也阻止 optional 降级。已撤销身份不得重新绑定其他 Intent；新任务使用新的受信会话身份，不复用旧身份清理 taint。原本已绑定的安全状态、序号与污点不因撤销清空。

并发线性化点为本地可信绑定解析：同进程 Store 的解析持读锁、撤销持写锁；撤销返回后开始解析的请求不得使用旧授权。已经取得快照的并发请求可能先于撤销被授权；该机制不取消已发出的允许决策，不提供覆盖真实副作用的原子执行租约。原有 hold 状态重查通过同一解析器观察撤销；历史合法动作的 Observe 仍按原决策及幂等规则记录，不把撤销误作抹除已发生事实。多进程仅依赖独占发布和每次读回，不能宣称跨进程读写锁或恶意同 UID 隔离。

HTTP 请求/撤销记录分别遵守 `intent-binding-revoke-request.v1.schema.json` 与 `intent-binding-revocation.v1.schema.json`。回执使用既有可选扩展与稳定 reason_code，不重签历史回执。


## Provenance-Bound Effect V1 — A1 授权硬门禁（2026-09-08）

依据用户[当前开发模板](templates/provenance-bound-effect-v1-development-template.md)与 ADR-015，覆盖此前 audit/warn 对 authority failure 转 allow 的语义。只改变新决策，历史已签回执按原字节验签，不重写历史。

先分类可信 Authority 与普通 Policy。required 缺绑定、缺失/篡改/过期/撤销/身份范围错误的已绑定 Intent，以及不能识别的 resolver 错误，均为 Authority invalid，任何 mode 实际 deny、无 advisory allow。optional 从未绑定且无错误时为 unbound_legacy，继续 Grant 逻辑。合法授权中的工具/效果/资源/参数约束不满足属于 Policy deny，仍按 audit/warn/block 处理。新 context/provenance 完整性失败接入同一门禁，不复制第二个授权器。

新 decision 回执使用可选签名字段 authority_status（valid/invalid/unbound_legacy）、authority_reason_code、policy_action、effective_action。Authority invalid 时不执行 Policy evaluator，policy_action 缺省；effective_action 与实际返回 action 一致。新正常观察与 hold resolution 同步实际 action，历史缺字段回执仍可读取。所有新字段沿用既有 Chain/canon/signing。

比赛 Dashboard 的兼容性增量：`POST /v1/decide` 响应增加可选 `trifecta`，直接投影本次签名 Receipt 的同名对象（`private_data`、`untrusted_input`、`egress` 三个布尔值；无状态时可为 null）。不接受请求侧提供状态，不重新推断，不改变判定顺序或 Receipt 合同；历史客户端可忽略该字段。显示字段本身不替代签名回执验证。

### caller cwd 边界

请求 Context 为 observational。删除 caller cwd 的 filesystem allow 捷径；工作区写权限必须由受信 Grant 明确授权，合法 ContextAssertion 也不能突破 Grant ∩ Intent。保持日志脱敏，不持久化额外 cwd 明文。新上下文签发/验证将在 A2 独立包实现。

## Provenance-Bound Effect V1：A2 可信上下文

`context-assertion/v1` 仅声明 `workspace_root`，由管理 capability 签发并在状态目录 `context-assertions/` 追加保存。V1 使用本地签名身份，issuer_id 固定为 `local-admin`；不声称支持任意外部 host attestor。Decision 调用只能提交 `context_assertion_id` 引用；普通 `context` 始终是观测信息。未知引用、签名/结构错误、到期、范围或请求绑定不匹配进入 Authority Hard Gate。

管理端 `POST /v1/context-assertions` 接受完整未签名合同，服务端设置 signing_schema/signature；`GET /v1/context-assertions/{id}` 读取签名记录，两者均要求 admin。请求绑定为 canon.Marshal 后的 SHA256，字段固定为 platform/session_id/agent_id/task_id/tool/tool_call_id/params。task_id 从已验证 Intent binding 派生；使用 assertion 必须存在可信 Intent 和非空 tool_call_id。不同任务、会话、工具调用、参数不能复用 assertion；同一调用在到期前允许幂等重试和审批复查。它不是一次性执行租约。

签名 workspace_root 是绝对路径，不补充 Grant 权限，也不修改 Intent 约束，授权仍取现有 Grant 与 Intent。回执仅持久化 assertion_id，不增加原始工作区路径。审批执行前继续验证该引用的签名、时效、范围和完整请求绑定；历史无引用回执保留旧签名语义。状态容量 4096、单记录 64 KiB，超额失败关闭；使用同目录 fsync 临时文件后排他发布，重启直接读取验签。

## Provenance-Bound Effect V1：R 统一动作描述

`runtimeaction.Describe(tool, params)` 为工具语义的唯一入口，输出 Tool、Operation、Effects、Resources、Egress、Mutating、ShellLike 和 HighImpactParameterPaths。Normalize/ExtractResources 仅作为旧调用方的兼容入口，委托同一描述实现。Grant/taint/trifecta/审批复查消费描述中的 Hosts/Paths/FilesystemWriteHint，不再各自维护工具表或命令正则。Hosts/Paths 是保守文本提示，只能增加检查，不作为结构化资源证明；Resources 仍仅来自已识别的结构化字段，解析错误显式保留。

shell、sh、bash、python/python3、node、powershell/pwsh 等解释器至少 process.exec + unknown，即使文本看似简单也不能宣称完整效果。Mutating 对解释器保守为 true；FilesystemWriteHint 表示文本发现的文件写提示，不代表无该提示就无文件副作用。高影响参数以排序 JSON Pointer 输出，覆盖 recipient/to、host/destination_host/url、文件目标、database_scope、credential_ref、deployment_target、repo/branch、command/cmd、account/identity；未知工具的这些显式参数仍参与来源约束。路径和值不写入独立日志；回执资源继续以摘要存储。

## Provenance-Bound Effect V1：B1 来源合同与约束基础

来源 taxonomy 与 trust 独立校验；不得根据 USER/MCP 等字符串推导 authority。参数来源记录只允许 parameter_path 和 provenance_refs，路径为 RFC 6901 JSON Pointer，绑定内容以现有 canon.Marshal 的 SHA256 验证。所有引用都必须通过后续可信 store 验签、issuer/scope/时效校验后才能交给 matcher；普通调用方提交的 Assertion 不视为已验证。minimum_trust 的顺序为 unknown < untrusted < trusted < authoritative；required 缺字段或缺引用拒绝，来源集合不匹配、内容摘要不匹配或 unknown derivation 拒绝。多个引用必须全部满足约束，不能混入一份可信引用掩盖低可信引用。

签发者 registry 数据模型包含 public_key（外部 Ed25519 公钥）或 local_key_ref（二选一）、allowed_source_types、max_trust_level、完整 scope、expires_at、revoked_at；具体发布与验签由管理端持久化模块实施。Decision 上报仅允许 MCP/WEB/TOOL/AGENT/UNKNOWN 且最多 untrusted，不接受 caller 指定 USER/TRUSTED_IAM 等授权来源。

### B1 签名验证边界

Assertion.VerifyAuthority 接受来自管理面可信 registry 的 Issuer 与本地公钥，不接受 decision 请求内嵌的 issuer。外部公钥严格 base64 解码为 32 字节 Ed25519；本地引用只识别 `local-state`。Issuer 的完整 scope 必须与 assertion、当前请求完全一致；来源类型必须被允许，trust 不得超过 issuer 上限。Issuer/Assertion 都检查时效；任何非空 revoked_at 都拒绝。声明过期不能超过 issuer 过期，未来 issued_at 拒绝。

验签使用原 signing.VerifyWithSchema/canon；结构校验拒绝未知 signing_schema、空/重复/自引用父节点、超限父节点、direct 带父节点以及 transformed/aggregated 无父节点。此阶段仅验证单节点授权；父节点签名、派生信任上限与深度/容量由后续图解析器验证，单节点验签不代表完整 lineage 已验证。

### B1 不可变签发者 registry

`provenance.Open(stateDir,key)` 在状态目录建立 provenance-issuers 与 provenance-issuer-revocations。Registry entry 使用 provenance-issuer-record/v1 envelope，内容为 issuer，管理身份签名；撤销使用 provenance-issuer-revocation/v1 envelope，包含 issuer_id、原签名记录摘要和 revoked_at。两者均复用 canonical signing。注册 ID 不可覆盖，重试同一内容返回原记录；同 ID 改内容冲突。撤销终态，不改写原 issuer 文件；每次 GetIssuer 验证原记录和撤销记录，无法读取或篡改拒绝。进程内读写锁保证并发顺序，跨进程的排他硬链接保证文件不覆盖；单 daemon 的既有 writer lock 仍是生产写入边界。

写入采用 0600 同目录临时文件、fsync 后硬链接排他发布；不支持硬链接即失败，不回退为覆盖。读取只接受普通文件、单 JSON 文档、已知字段，最大 64 KiB；最多4096个签发者。状态文件签名证明完整性，不提供对同 UID 恶意进程的防删除/整目录快照回滚隔离。

### B1 声明图存储与解析

声明按完整 Scope 的 canonical SHA256 分目录存于 provenance-assertions。每个 scope 最多1024节点、4096条父引用边、32父节点和64层深度。新节点发布前验证当前 issuer、全部父节点与同 scope，禁止 trust 高于任一父节点，禁止子节点有效期超出父节点；unknown 派生必须保持 unknown trust。派生 source type 只能保持父类型或显式降为 AGENT/UNKNOWN，不允许把 MCP 重标为 USER。

IssueAssertion 仅供后续管理面调用，使用已注册 local-state issuer 签发；ImportAssertion 接受外部签名，必须通过 registry 公钥验证。Resolve 每次重读并验证整个父图，不保留跨请求信任缓存，故父 issuer 撤销/过期会使子图即时拒绝。未找到、环、容量、篡改均失败关闭；同 ID 同签名内容可重试，冲突不覆盖。HTTP 暂未接入，普通 decision 上报必须走后续受限入口而不能调用管理签发函数。

### B2 参数联合匹配

Store.MatchParameters 在一次 registry 读锁内验证所有 parameter_provenance：路径唯一、每路径1–32个唯一引用、总路径不超过1024；路径必须实际存在，引用必须与该参数的 canonical 内容摘要相同。所有引用及父节点都验证，不能忽略未被约束的伪造引用，也不能只挑一个高可信引用。匹配期间的 issuer 撤销与写入被序列化，下次调用重新读取当前状态。

每条约束先校验路径/source taxonomy/minimum_trust；required 且参数或绑定缺失返回 provenance_missing。存在绑定时每个引用都必须满足 allowed_source_types 与 minimum_trust，unknown derivation 返回 provenance_derivation_unknown。此方法只做参数来源约束，不替代 Grant/Intent 的值约束或 RuntimeActionDescriptor。V3/runtime 接线另行实施并端到端验证。

### B2 Intent V3 双读与执行门禁

新增 intent/v3 合同，基于 V2 字段新增必需 provenance_constraints 数组（允许显式空数组）。Go 使用指针数组区分旧版省略与 V3 空数组；V2 不得携带该新字段，历史 canonical 签名不变。每条来源约束以唯一 parameter_path 指定 allowed_source_types/minimum_trust/required，复用 provenance.Constraint.Validate。

任何 V3 在参数来源检查器未配置时拒绝，不允许先签发 V3 再把它当 V2 执行。Decide 接受 parameter_provenance 的引用绑定，使用已验证 Intent 的 task_id 和请求 platform/session/agent 构成范围；由来源 Store 对所有引用与约束执行匹配。无效/缺失必需来源进入 Authority Hard Gate。回执持久化绑定引用，审批执行前用原始回执绑定和当前参数重新验证，不能在 hold-status 临时替换来源。普通 V2 无新引用时保持原行为。

### B1 管理 HTTP 接口

新增管理 capability 路由：POST /v1/provenance-issuers 注册，GET /v1/provenance-issuers/{id} 读回，POST /v1/provenance-issuers/{id}/revoke 终态撤销（空 JSON 对象）；POST /v1/provenance-assertions 本地签发，POST /v1/provenance-assertions/import 外部签名导入。POST /v1/provenance-resolve 接受 provenance_id 与完整 scope，返回经过当前 issuer/父图验证的声明。管理输入严格拒绝未知字段、多 JSON 文档和超过64 KiB的正文。

以上接口均为 admin，决策 token 返回403。状态错误对外只输出稳定 provenance reason_code，不暴露文件路径或底层异常。来源普通上报另设受限接口，不能复用管理签发接口。生产 Server 与 Engine 打开同一状态目录的 provenance Store；均逐次读取签名记录，不引入独立数据库或新的裁决服务。

### B1 受限来源上报

POST /v1/provenance-reports 使用 decision capability。正文包含 report_id、platform/session_id/agent_id、source（type/source_id/trust）和 content（JSON值）。服务从已验证且当前有效的 Intent binding 派生 task_id，不接受 caller task/issuer/signature。仅允许 MCP/WEB/TOOL/AGENT/UNKNOWN，trust 缺省为 untrusted，不能超过 untrusted；来源类型不在允许集合时直接拒绝。

服务为该完整 scope 使用专用 report issuer（local-state、五类低可信来源、untrusted ceiling、到期不晚于 Intent），不允许请求选择其他 issuer。source_id 在签名声明中只保留摘要标识；content 仅存 canonical 内容摘要，不持久化原文。声明有效期最多15分钟且不晚于 Intent。report_id 在 scope 内幂等，同 ID 不同内容冲突；同 ID 的过期重试拒绝，调用方为新的采集生成新 report_id。上报是 self-reported 输入记录，不证明真实 MCP 服务身份或实际执行，不能赋予工具效果独立证据地位。

### B2 确定性低可信内容选择

Store.Select 从已验证的低可信父节点中派生参数：调用方重送原始 JSON，服务先比较完整 canonical digest，再按严格 JSON Pointer 自行提取值并计算子摘要。调用方不能指定输出值、类型或 trust。V1 选择入口限于 MCP/WEB/TOOL/AGENT/UNKNOWN 且最多 untrusted、本地签发的来源，不能借低权限入口使用可信 USER/IAM issuer。

子节点继承父节点 source type/trust、scope、issuer 和时效；source_id 记录 parent_id+pointer 的摘要，provenance_id 由该选择身份与完整 scope 确定。已知 lineage 标记 transformed；unknown 父节点继续 unknown。同一选择可幂等重试，原文和被选值不落盘，父节点撤销/过期/篡改立即拒绝。后续 MCP 集成调用此确定性方法连接工具结果与高影响参数。

HTTP 入口为 POST /v1/provenance-select，使用 decision capability；请求仅含 parent_id/pointer/platform/session_id/agent_id/content。服务从当前 Intent binding 派生 task_id，严格64 KiB读取；拒绝额外输出值或权限字段。

### B2 MCP 本地协议集成验收

新增隔离验证脚本，通过本地 loopback MCP JSON-RPC 服务执行 initialize→notifications/initialized→tools/call，取得实际协议结果，再经生产 SIQ daemon 的 Report→Select→Intent V3→Decide。复用现有集成 Harness 的临时状态、准入、Grant 人工 challenge/approve/deploy 与绑定流程，不使用真实平台配置或付费模型。

该验证固定 MCP 2025-06-18 的 HTTP JSON 响应分支；不声称实现通用 Streamable HTTP/SSE 客户端、OAuth 或 native 平台自动采集。协议依据为官方 [transports](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports) 与 [lifecycle](https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle)。报告标注 component_fixture，只存动作、reason code、哈希与检查结果，不保留原始工具内容或凭据。MCP endpoint/tool 身份由测试实际连接配置构造；上报仍不具备独立 attestor 权威。

### B2 高影响参数默认约束

V3 对 RuntimeActionDescriptor.HighImpactParameterPaths 中每个实际出现且没有显式来源约束的路径，补 required=true、minimum_trust=trusted、allowed_source_types=[USER,SYSTEM,TRUSTED_IAM,TRUSTED_DATABASE]。显式签名约束按精确 JSON Pointer 覆盖该路径的默认值，因此业务可明确许可特定 MCP/untrusted 来源；没有显式许可时不能由低可信输入控制高影响参数。

默认值只作用于 V3，不静默改变 V2 历史语义。Provenance 模块直接消费 runtimeaction.Descriptor，不建立第二套工具/字段分类。默认约束为每次动作生成的新副本，不修改已签名 Intent 的数组或摘要。空 provenance_constraints 在合同上仍有效，但不表示高影响参数无需来源授权。

### C1 EffectEvidence 合同（运行时待接入）

按 ADR-0017 定义 `effect-evidence/v1`，关联 action_id 与 decision_receipt_id，分离 execution_state/source/independence/coverage/result。工具自报只允许 self_reported + unknown coverage/result；unknown 来源不提升任何证据维度。签名、observer 权限、动作关联和资源匹配必须由后续运行时验证，schema 合法不代表完成任务。新增 API 和存储尚未上线；现有 Observe 保持原语义。

C1 资源引用冻结为 `filesystem|network|message:sha256:<64小写hex>`（实际格式如 `filesystem:sha256:…`），直接复用 RuntimeAction ResourceRefs 的 domain/digest，不保存原始路径、收件人或 URL。EffectEvidence 结构校验必须严格解析 RFC3339 时间、拒绝未来观察、未知字段/多文档，并通过原 signing/canon 验签。单条证据验签不能替代 observer capability 与动作匹配。

### C1 决策关联与效果分类

Engine 的 EffectAction 仅从已签发或经回执链恢复的动作状态读取，要求精确 action_id+decision_receipt_id，沿用24小时动作关联窗口；未知、过期、错配引用拒绝。输出包括决策时间、task、效果集合和资源摘要，不包含参数原文；hold 只有已批准才视为动作授权。

效果提交必须与管理端指定的 observer Source 完全一致，正文不能改变 source_id/type/independence。独立 completed 证据若关联未获授权动作，保留为 unexpected 并给出 unauthorized_effect_observed；效果类型或资源不匹配为 unexpected/effect_scope_mismatch，不能记为预期完成。观察时间不得早于关联决策。分类器只返回待存储记录与 finding code，后续存储/API 必须将两者作为同一不可变事实处理；本次分类器不单独写 finding。

### C1 不可变证据存储

`effect-evidence/` 中每个 ID 对应一个0600不可变签名封套，包含 evidence、finding_code、request_digest、task_id。外层签名将事件与证据绑定，内层签名保持 EffectEvidence 合同独立可验证；request_digest 为原始无签名提交的 canonical SHA256，用于防止分类归一化掩盖冲突。相同 ID 相同请求返回既有记录，变化请求拒绝；重试不会改写历史事件。

先完整写暂存文件、fsync、关闭，再同目录 os.Link 排他发布。无覆盖回退；暂存文件不算有效记录。读取拒绝符号链接、超限、多文档、签名错误与 ID 错配。单状态目录最多8192份记录，进程内多 Store 共享锁；跨进程仍依赖 daemon writer lock。同 UID 目录整体删除/回滚和机器断电的目录项持久性不作为本实现已解决的保证。

### C1 observer capability 与 API

Admin POST `/v1/effect-observers` 管理签发短期 observer token，请求固定 source 和完整 platform/session/agent/task scope。仅允许 host_observer/host_independent、openshell/host_independent、provider_audit/external_independent、test_oracle/external_independent；source_id由管理员指定。有效期1–3600秒，最多128个活动 token；内存仅存 token SHA256，服务重启全部失效。DELETE `/v1/effect-observers/{id}` 立即撤销。生产 observer 需管理端重新配置，不自动延续。

POST `/v1/effect-evidence` 仅 capEffectObserve，scope 必须精确匹配 Engine 动作，Source 必须与 token 配置一致，提交 Evidence signature 必须为空。GET `/v1/effect-evidence/{id}` 与 GET `/v1/actions/{id}/effect-evidence` 为 admin 读取。普通 decision/admin token 均不能代替 observer 提交。撤销与提交共享 observer 锁，撤销返回后的请求不再落盘。签发响应 no-store，不记录明文 token。

### C1 文件观察器

复用 ADR-013 的普通文件打开保证，抽为 internal/fileopen，准入扫描继续使用相同实现。文件 observer 拒绝路径任一可见符号链接、非普通文件、读取超预算以及打开/读取期间检测到的身份或 size/mtime 变化；Unix 保留 NOFOLLOW/NONBLOCK，Windows 保留已说明的残余 TOCTOU。

Capture 仅输出资源摘要、存在性、内容 SHA256、size、mtime 和采样时间；文件原文及路径不落证据。前后资源必须一致，后采样时间不早于前采样；最长读取16 MiB。FileWrite 对比可信预期摘要：后文件缺失为 failed/unexpected；发生可见变化且摘要匹配为 completed/expected，不匹配为 completed/unexpected；前后无可见变化为 unknown/unknown，不能证明重复同值写已执行。coverage 固定 partial，independence 由受信 host observer 注册为 host_independent；同 UID 攻击者与采样间隔内瞬态变化仍属残余风险。

C1 文件材料附加：不可变 Record 增加可选 file_observation（file-observation.v1 合同），旧记录缺省时保持签名字节不变。SubmitFile 将观测材料、摘要证据与 finding 同封套保存，读回重新验证材料计算的 evidence_digest、资源、时间与执行状态。相同 ID 的普通摘要提交与带材料提交不可互换；拒绝把后来补充的材料伪装为原始记录。材料只含摘要/元数据，不含路径或文件原文。

### C1 文件采样 HTTP 生命周期

capEffectObserve 新增 POST `/v1/file-observations`（observation_id/action_id/decision_receipt_id/path/expected_digest/max_bytes），服务端验证固定 host_observer、完整 scope、file.write 效果和路径资源摘要匹配真实动作后，实际 CaptureFile。POST `/v1/file-observations/{id}/finish`（path）再次读真实文件并 SubmitFile，客户端不得上传前后快照。前置采样不授权执行，deny 动作仍可观测并记事件。

待采样记录仅保留摘要快照、动作引用、预期摘要和 token 归属，不保存明文路径。最多128条，随 observer token 到期/撤销失效；服务重启失效并要求重新开始，禁止把丢失的前置采样补成成功。完成后的持久化证据仍可读回；同 token 完成重试返回原证据，不重新采样改写结果。持久化 pending 与跨重启继续采样尚待后续恢复实现。

### C1 受控网络 oracle

NetworkOracle 仅用于本地 benchmark，绑定127.0.0.1随机端口，对外名称仅允许 localhost/127.0.0.1；记录随机私有路径上实际收到的请求。监听器配置决定最终scheme/host/port/resolved_target，不信任客户端 Host 头对最终目标的声明。每个接收事件生成服务器 request_id，保存方法/URI/正文的组合摘要与接收时间，不记录正文或URI原文；1 MiB请求体、64事件预算，超限拒绝且不生成完整接收证据。

网络证据来自该 oracle 的事件对象，source=test_oracle/external_independent、coverage=partial。requested endpoint 与 final endpoint 分开；最终资源引用复用 runtimeaction 的 network host摘要。目标scheme/host/port变化分类为 unexpected；共享主机不同端口也保持差异，不能由旧 host-only 资源匹配掩盖。此为固定本地服务证明，不推广为通用互联网、provider审计或native平台支持。

### C2 签名效果验证要求

Intent V3 增加可选 effect_requirements 数组（最多128项、requirement_id唯一），缺省/空数组表示没有声明效果要求，Completion返回unknown/not_required。显式null拒绝；V2拒绝该字段，包括null，旧V3缺省保持签名字节不变。

第一阶段要求明确 file.write、filesystem资源摘要、预期文件内容SHA256、minimum_independence（host_independent或external_independent）和minimum_coverage（partial或full），所有字段必填，不把缺省值解释为更低要求。效果必须在 allowed_effects 中；要求不扩大运行时授权。网络要求在服务器接收材料归档后另行扩展，暂不声称已支持网络任务完成证明。

### C2 Completion 聚合规则

聚合器接收管理端已验证 Intent 投影（task_id/intent_id/digest/requirements）、当前验签有效的 Record、Engine 动作查询和验证公钥；任何调用方正文不能替代这些依赖。对全部输入记录先验签，再按 task 过滤；动作必须匹配 task、Intent ID/digest、action/receipt、资源和 file.write 效果。无要求为 unknown/not_required。

每项要求至少需要一份 completed/expected、无 finding、独立性与coverage达到要求、FileObservation 与证据绑定且实际后文件摘要匹配签名预期的证据才能 verified。无证据或文件缺失为 incomplete；已知越权/目标内容冲突为 conflicting；验签或关联失败直接错误，材料缺失/等级不足或未知执行为 unknown。冲突优先于unknown，unknown优先于incomplete，全部满足才verified。未知证据不得被一条正例遮蔽；同任务其他资源的已知安全事件也阻止整体verified。

这是确定性状态投影，不写 completed 字段、不执行模型判断。当前动作查询仍受24小时窗口限制，超窗关联不得制造完成证明；历史查询恢复另行补齐。

### C2 任务查询 API

Admin GET `/v1/tasks/{task_id}/completion` 查验签名 Intent、按task读出并验签全量有界证据、关联Engine动作后返回 completion-status/v1。未知任务404，同task对应多份Intent返回409（不擅自挑选较宽要求），损坏Intent/证据或缺失动作关联返回通用500并拒绝完成判断。decision/observer凭据不能读取管理任务投影；接口仅GET，不能写 completed=true。

查询反映已发生效果对已签名要求的满足情况，不是新的执行授权；当前动作关联窗口仍是24小时。状态不缓存，新的失败/冲突证据会影响后续查询。跨存储并发读不是全局快照，结果仅代表本次读到的已发布证据；任务冻结/最终封账不在本轮最小模型内。

### C2 历史动作复核

Completion 使用 HistoricalEffectActions 按本次证据引用集合单次扫描整条签名回执链，最多8192个引用；历史查询不依赖24小时内存动作缓存。要求精确decision action_id/receipt_id以及hold_resolution对原决策的引用和scope一致；重复决策/重复审批或链校验失败拒绝。扫描结束与当前进程已知链头比较，防止运行中截断被误当完整历史。

HistoricalEffectActions 只生成只读投影供已保存证据复核，不重新注册动作、不延长 Observe/hold-status/新证据提交的执行窗口。新请求继续用 EffectAction。完整目录回滚后重启的保护仍取决于既有可信checkpoint，不能把内存链头比较宣称为永久防回滚。

### C2 审批生效时间

动作投影增加仅服务端派生的 AuthorizedAt。普通允许动作取决策时间，hold获批取签名hold_resolution时间；新审批记录使用RFC3339Nano保留亚秒精度。当前缓存、重启恢复和历史扫描均从同一签名时间恢复。独立completed效果若observed_at早于AuthorizedAt，记录unauthorized_effect_observed；Completion也复核该关系，旧expected证据不能因后续获批变成verified。旧秒级审批记录仍只能提供秒级历史精度，不伪称能恢复当时未记录的亚秒顺序。

### C1 网络观测材料归档

Record 增加可选 network_observation：请求的scheme/host/port与真实接收事件（最终scheme/host/port/resolved_target、server request_id、请求摘要、接收时间）。不存请求路径、查询串、正文或完整URL。NetworkOracle.Material 只读取自身收到的事件；SubmitNetwork 将材料、效果和finding同封套签名，读回重新派生摘要/资源/时间/结果校验。文件/网络材料互斥；旧记录省略新字段保持签名兼容。当前只验证 loopback test_oracle，不扩展为生产公网审计。

### C1 网络材料提交 API

POST `/v1/network-observations` 使用capEffectObserve，正文只含observation_id、action_id、decision_receipt_id、observation。Source从已注册observer派生，必须为test_oracle/external_independent，scope精确匹配真实动作；server request_id绑定该Source。调用管理端信任的独立测试服务器上报材料，不赋予decision token上报权限，不由此宣称接受任意客户端日志为独立真相。SubmitNetwork原子保存材料/证据/事件，同ID冲突409，来源/scope错误403。

### C2 网络完成要求

Effect requirement 增加 network.request 分支：resource_ref 为 network 主机摘要，expected_digest 为受控服务器请求组合摘要（method、URI、body_digest 的 canonical SHA256），expected_endpoint 必须包含 scheme、规范化 host、十进制 port。最低独立性必须 external_independent。file.write 不接受 expected_endpoint，旧文件要求签名表示保持不变。

Completion 对已验签网络材料同时比较签名 endpoint 与 requested/received 两端、request_digest 和真实动作资源；缺少材料 unknown，端点或摘要不符 conflicting。不得仅凭主机摘要匹配忽略端口/协议，也不得让上报者自行选择的 requested endpoint 替代签名要求。当前网络材料仅支持受控 loopback oracle，partial 覆盖不能满足 full 要求。

### C2 文件pending持久记录（恢复基础）

新增签名 file-observation-pending/v1，保留observation/action/decision引用、完整scope、固定observer source、原owner token摘要、服务端before快照、expected_digest/max_bytes和原到期时间；不保存原始路径、文件内容或token。不可变发布到effect-evidence-pending目录，0600文件，独立8192条归档上限；同ID同内容幂等，任何字段变化冲突。

该记录是恢复依据，不是新的执行授权；读取过期记录供诊断不延长采样有效期。恢复仍必须验证当前observer凭据、source/scope、动作与原deadline；跨token接管与撤销终态需后续管理API接入，在此之前持久记录不能自动被任意新observer续用。

### C2 begin写前持久化与原快照重用

文件begin先检查已签名pending记录。同ID且owner/source/scope/动作/预期摘要/预算/资源一致、原deadline仍有效时，仅重用原before并恢复内存索引，返回200；不重新读取文件、不延长deadline。不同owner或元数据冲突409，损坏记录失败关闭。首次采样必须SavePendingFile成功后才返回201和建立内存索引。Server重启导致原token失效，新token不能以begin隐式接管旧快照；显式管理恢复仍须后续接入。

### C2 observer撤销持久终态

DELETE effect-observers/{id}在删除内存凭据前发布effect-observer-revocation/v1签名记录，字段仅owner_digest、revoked_at和签名元数据，独立effect-observer-revocations目录8192条预算。撤销记录不可覆盖，同owner重试返回原记录；损坏状态失败关闭。后续pending恢复必须检查原owner与接管owner的终态，不能通过注册相同source的新token复活被撤销采样。新token注册本身不撤销旧终态，也不自动获得旧pending。

### C2 显式pending接管历史

恢复使用file-observation-recovery/v1不可变签名链，不改原pending：observation_id、pending_digest（完整已签名pending的canonical SHA256）、sequence(1..64)、previous_hash（前一完整recovery的canonical SHA256，首条全0）、owner_digest、recovered_at与签名字段。时刻不早于原采样/前一接管且早于原deadline；相邻owner必须不同。任何断链、替换pending、损坏签名或超64次拒绝。

后续管理恢复端点必须验证当前observer固定source/scope及原始和全部历史owner的持久撤销终态；原owner或历史接管owner已撤销，不允许新token继续该pending。记录先持久发布后再更新内存owner。重复当前owner幂等，不能借恢复延长原deadline。此节定义接管模型；API、存储发布及强杀测试按后续实现落地，不提前宣称可用。

接管存储使用原pending旁的独立子目录，按六位sequence排他发布签名JSON；读取必须验证连续序号和完整链。存储层接管使用expected_owner进行比较后追加，防止并发不同接管者覆盖；当前owner的同内容重试幂等。读取有效owner及追加都复核全部历史撤销与原deadline，损坏状态失败关闭。存储不代替管理端的source/scope和动作有效性复核；同UID删除整个历史的回滚防护仍属于既有可信状态目录边界。

管理恢复接口：POST /v1/file-observation-recoveries，仅admin；请求observation_id、observer_id（当前已签发session ID）、expected_owner（当前owner摘要）。不接收原始token或路径。验证目标observer未到期/未撤销、原pending完整source/scope一致及fileAction历史动作关联，随后执行存储CAS接管。返回200包含recovery签名记录与原expires_at；不得延长期限。已完成效果拒绝恢复409。begin/finish均复核持久owner和全部历史撤销，不能仅凭内存缓存；恢复后由新observer调用begin重建索引，复用原before。完成记录已发布而缓存Completed未更新时，finish返回已签名记录而不重新采样。

### D 决策阶段性能采样

Engine.Options可选StageTiming回调仅由宿主测试/基线程序注入，不接受请求参数，默认关闭。以Go单调时钟time.Now/time.Since测量实际执行的intent_lookup、authority_validation（lookup之后的绑定/合同校验）、runtime_action_normalization、context_validation、provenance_resolution、policy_evaluation和receipt_append_fsync。未进入的阶段不报0；回调在引擎锁内同步执行，宿主必须非阻塞且不可重入引擎。阶段不改变签名回执或授权时间源，耗时只用于性能统计，不作授权输入。效果处理单独由效果存储层接入，完整P50/P95/P99报告后续由真实采样聚合。

效果阶段基线在受控测试中以单调时钟直接包围Store.SubmitFile，包含材料转Evidence、相关性检查、签名及持久发布，排除调用前的采样和调用后的日志。独立构造的Action明确标注为组件微基准，不将其称为全链路性能。基线分别预热5次、采集100次，完整原始样本和nearest-rank P50/P95/P99一并导出；没有实际样本或数量不符直接失败，不填入虚构延迟。

### B 全局Intent撤销

intent-revocation/v1不可变终态记录包含intent_id、intent_digest、revoked_at、reason_code=intent_revoked及canonical签名；不修改原Intent或各binding。RevokeIntent(id, expected_intent_digest)在authority写锁下发布，错误摘要冲突、同摘要重试返回原记录；沿用4096条容量和私有排他发布。Bind拒绝已撤销Intent；ResolveBinding每次在同一authority读锁内复核全局终态，返回已验证Contract和Binding元数据供签名deny使用。普通Get/List保留历史合同读取，不能将历史读取当作当前有效授权。损坏/摘要不匹配撤销记录intent_revocation_invalid失败关闭。原绑定撤销优先保持既有错误码；无全局撤销记录的V2/V3不改变行为。新API与多会话fixture后续接入；检查完成前已取得的执行快照不构成原子取消保证。

全局撤销管理路由：POST /v1/intents/{id}/revoke，请求仅expected_intent_digest；GET /v1/intents/{id}/revocation读取已签名终态。两者均复用现有capAdmin保护，decision/observer不得撤销或读取管理状态；方法不符405，错误摘要409，未知Intent/撤销记录404。重复POST返回同一签名与时间。原GET /v1/intents/{id}保持历史合同读取语义；runtime ResolveBinding及holdAuthorityCurrent使用当前撤销状态，三模式均hard deny。

### B Hermes宿主来源引用桥接

pre_tool_call增加可选宿主关键字parameter_provenance与context_assertion_id，原样映射为Decide顶层引用，不从tool args/result或cwd推导可信来源，不传入内联Intent/issuer/trust。签名、scope和参数摘要仍由daemon验证。缺省不改变旧请求；显式提供引用但服务不可达、400或响应非法时必须block，包括warn/audit_only，避免引用校验失败退回legacy放行。该桥接不代表原版Hermes会自动生成这些字段；原生MCP捕获与传播仍须单独集成验证。

Hermes HTTP映射在发送前用严格JSON编码（拒绝NaN/循环/非JSON对象），请求UTF-8字节不超过1MiB；失败返回无有效裁决，由引用调用的硬拒绝分支处理。响应读取最多1MiB+1字节，超限视为无效，防止无界读取。此为传输预算与错误处理，不在适配器重新实现来源验签/授权策略。

### B Hermes显式MCP工具来源采集

适配器配置mcp_sources是精确runtime tool_name→部署者指定server/endpoint identity的映射，默认空；不按mcp名称前缀推断server（原生名称可能歧义），不从args/result接收该映射。post_tool_call对匹配项自动向/v1/provenance-reports提交实际result，source固定MCP/untrusted，source_id为server identity+tool canonical摘要；report_id绑定platform/session/agent/tool/call。超过64KiB、不具备稳定call ID或无法JSON编码的结果不登记、不截断后当完整来源。成功后仅在有界内存缓存保留provenance_id，通过provenance_reference(session,tool,call)供宿主显式传递；缓存不保存result/token，5分钟到期，2048条满时不丢弃旧引用、不声称采集成功。引用最终由daemon复验。采集失败不伪造来源且不阻止已经发生的工具效果；后续required引用缺失必须由V3拒绝。此配置桥接仍需真实原生MCP集成验证，不能称为任意服务器零配置支持。

Hermes显式携带Authority引用的调用，在决策关联缓存冲突或容量耗尽时也必须block，不能因warn/audit_only退回allow。拒绝不改变daemon裁决，不声称已执行工具；未携带引用的legacy调用保留原策略表。

### RuntimeAction参数遍历预算

描述器预检参数树：根深度0，最多64层、8192个值节点、单JSON Pointer最多1024 UTF-8字节、全部指针累计最多1MiB。超限返回runtime_parameter_budget_exceeded及unknown描述，不产生部分资源/高影响路径。Decide保留原参数摘要和签名拒绝回执，跳过参数文本扫描、Intent参数校验和policy，三模式均hard deny。直接Intent检查同样拒绝预算异常。该预算不提高任何资源权限，不将截断结果当作完整描述。

### Completion同动作矛盾材料（2026-09-08）

同一效果要求中，同一action_id与decision_receipt_id同时有满足要求的完成材料和独立失败材料时，保留双方Evidence IDs并返回conflicting/effect_evidence_conflicting。仅失败材料仍为incomplete；不同动作的成功/失败不因此自动认定矛盾。失败方必须附实际文件/网络材料且满足要求的独立性/覆盖范围，不能凭工具自报制造独立冲突。该判断表示材料不一致，不裁定先后观测变化的业务原因，不改变历史授权。

E-05补充：已签名记录中的tool_report/self_reported、execution_state=completed表示工具的成功声明，仍要求coverage/result为unknown，不能证明实际成功。若同一动作和决策回执存在满足上述独立性与覆盖要求的实际失败材料，则声明与材料构成冲突，Completion返回conflicting并保留双方引用。成功声明单独存在仍为unknown；仅有无材料的失败声明不构成此类冲突；不同动作不混合比较。本轮以独立文件采样确认输出未出现验证该分支，不宣称具备通用网络未接收证明。

POST `/v1/tool-effect-reports` 使用capDecision，合同为tool-effect-report.v1（复用effect-evidence-submit/v1字段）。仅允许tool_report/self_reported、coverage/result=unknown、空signature；source_id是未验证的工具声明标签。动作与回执必须由Engine历史台账解析并匹配，其他source拒绝，不能提交独立采样材料。沿用64KiB解析预算、8192条不可变效果存储预算与重放冲突规则。返回签名effect-evidence-record/v1记录，签名仅证明收录该声明，不证明声明属实。该历史效果记录入口允许撤销后补报已发生动作，不创建或恢复执行授权；无有效历史动作的声明拒绝。管理或observer凭据不能代替decision凭据。

### Runtime 参数来源的 scope 拒绝码

MatchParameters 对调用方明确提供、但无法在当前 platform/session/agent/task 目录解析的 provenance ref 返回 provenance_scope_mismatch。跨任务、跨会话及未知 ID 使用同一代码，不探测其他 scope 是否存在该 ID，不新增全局索引或目录扫描。代码含义是“引用无法绑定当前 scope”，不声称已确认该 ID 存在于其他任务。未提供必需引用仍为 provenance_missing，管理 Resolve 的未找到仍为 provenance_not_found；坏签名、过期及撤销保留各自明确代码。该调整只影响签名拒绝原因，不改变任何允许条件。

## Hackathon V3 integration: trusted message routing metadata

2026-09-08: the real Secure Agent integration exposed a false deny: the generic
parameter PII scan classified the authorized recipient mailbox itself as an
exfiltration payload. For `message.send` only, a top-level `recipient` or `to`
string can be omitted from the **new PII scan input** after valid Intent V3,
context and provenance validation, and only when its effective signed/default
provenance constraint is required and minimum trust is trusted/authoritative.
The existing provenance matcher must have verified all references, canonical
value digests, issuer signatures, full ancestry, scope and current validity.

This is routing-field classification, not data declassification. All parameters
still participate in secret and threat scans, normalized resources, Intent/Grant
checks, signed parameter digests and observations. The remaining message body,
nested fields and all other parameters still undergo PII scanning. No existing
session taint is removed. Invalid/missing/optional/untrusted provenance, V2 and
legacy requests receive the original full scan. `Observe` remains unchanged:
PII actually present in a tool result still taints the session. No email address,
contact name or competition-specific allow/reason code is hard-coded.
# Hackathon integration correction: per-Grant desired policy identity (2026-09-08)

Creating Grants for two different agent instances from the same admitted Skill
must create separate immutable desired policy namespaces. The initial policy
ID is `pol-` + the newly built Grant ID, consistent with PatchDesired's fallback.
It must not depend on Skill content hash alone: the selector includes the agent
ID, so that old naming reused version 1 for different immutable content and
failed the second creation. Existing stored Grants retain their signed policy
references; no old policy, Grant or version is rewritten. Approval, deployment,
selector checking and append-only publication remain unchanged. Tests must
cover different subjects/platforms sharing one admission and sequential actual
application tasks in one daemon.
# Hackathon approval integration (2026-09-08)

The admin-only `POST /v1/grants/{id}/require-approval` accepts the new
`grant-tool-approval/v1` request contract. Only pending Grants may be changed,
under their exact state revision and an identified human actor. Every named
tool must already have an allowed declared fact; this operation never grants
new tools. It adds signed `conditions.require_approval=true` to those facts.
Grant v1 already carries arbitrary conditions, so its wire shape is unchanged.
The existing receipt engine uses this condition on allowed declared/effective
tool facts as an additional per-use HOLD requirement on every platform. Existing
OpenClaw approval gates remain. Authority, provenance, context and data-policy
denials still take precedence. PatchDesired preserves an existing tool approval
condition when rebuilding that same tool. Existing challenge digests include
facts; mutations invalidate old challenges. Changes use CommitGrant with audit.

The closed built-in `verify_report` tool accepts only the versioned single-path
parameter shape. Its descriptor is file.read plus process.exec and includes the
filesystem target and required path provenance. Unknown parameters or invalid
paths fail closed. The application executor starts a fixed isolated interpreter
program to hash a bounded report file; callers cannot choose code, executable,
arguments beyond the report path, environment, or shell syntax. This capability
does not change normalization of exec/shell text (still includes unknown).
Process-start and returned digest are reported observations, not independent
process-effect evidence or OS containment. File/network Completion continues
to use the existing observers and exact immutable execution Intent.
### Hackathon structured resource hints (2026-09-08)

Real model reviews exposed a false denial: a `write_file` report body mentioning
`/workspace` was treated as another filesystem target. Structured file tools
derive Grant path hints from their `path`/`file_path` parameters and validated
filesystem resources, never from report/content strings. File payload URLs do
not imply a network effect. Known network tools derive host hints from `url`/
`host`; message bodies do not create extra destination hosts. Interpreter tools
retain conservative full-command hints and unknown effects. Full parameter text
still participates in threat/secret/PII scanning, digests and provenance checks.
This changes resource selection, not taint policy or authority requirements.

### 个人实例接入增量（ADR-023）

带 `instance_id` 的接入预览返回 `local-adapter-plan/v2`，应用与恢复绑定同一实例，按实例隔离操作记录；旧默认预览继续 v1。原生 CLI 只处理配置副本，由已有事务应用用户确认的输出。原生配置解析证据不能替代实际工具调用自检。

### 个人运行自检与授权期限增量（ADR-024）

运行自检采用真实宿主会话，不以工具 registry 的直接调用替代钩子链路；控制器与临时授权边界见 ADR-024。公开 Hermes CLI 先以隔离实例验证，尚未接入用户实例前不得写入成功状态。

授权期限的前置实现：管理接口 `POST /v1/grants/{id}/expiry` 接收 `grant-expiry-edit/v1`，仅允许 pending_approval Grant 在精确 revision 下修改期限。duration_seconds 为 60–2592000 的整数，按服务器当前时间计算到期点；null 明确表示不设期限。期限写入已有 signed Grant.expires_at，与审计同事务。变更使既有批准 challenge 失效，不延长已批准或已部署 Grant，不产生 effective。

期限为半开区间：当前时间达到 expires_at 即不再可用；非法非空期限按无效处理，null 保持旧版无期限行为。挑战生成/消费、批准、部署及每次决策/hold 执行前重查均检查期限。旧回执继续可验证，不因后来到期否认历史已发生的操作。期限检查保持原 policy 模式语义：block 拒绝，warn/audit_only 只给出拒绝建议；无效或过期的必需 Intent Authority 仍在所有模式 hard deny。自检临时授权必须同时绑定独立短期 Intent，不能仅靠 Grant 字段保证撤权。

产品自检增量采用 `local-runtime-check.v1`：管理接口 `POST /v1/runtime-checks/preview`、`POST /v1/runtime-checks/start`、`GET /v1/runtime-checks/{id}`、`POST /v1/runtime-checks/{id}/cancel`；独立启动凭据接口 `POST /v1/runtime-checks/attach` 只绑定服务预定的检查身份与真实宿主会话，不能查询或修改通用授权。具体容量、确认、120 秒期限、摘要失效及崩溃恢复规则见 ADR-024。旧 adapter diagnostics v1 不回填运行成功状态。

管理查询 `GET /v1/runtime-checks?instance_id=...` 返回 `local-runtime-check-list/v1`，items 只含该实例最近一条检查或空数组，恢复前端刷新后的检查入口；读取 passed 结果时重新核对摘要。所有结果保留“仅本次调用边界”的含义，不能提升整个平台或 Skill 的保护等级。正常服务退出先取消并等待自检清理；崩溃恢复在既有 state writer 独占锁下进行。若绑定已提交而检查记录尚未保存其 ID，按该检查的独立 Intent 找回并撤销，不处理其他 Intent 的绑定。

清理失败可经管理接口 `POST /v1/runtime-checks/{id}/cleanup` 重试，始终不恢复执行或批准。所有自检 JSON 请求拒绝未知字段、尾随文档和超过 16 KiB 的正文；管理凭据与独立启动凭据不能互相替代。共享 Go 输出样例 `runtime-check-{plan,started,passed,attached,list}.json` 由 Python 合同测试校验，passed 必须具备结束时间、完整清理、五条关联回执与五项检查通过。

### 个人权限资源边界修正（ADR-025）

Grant 工具层文件读取与写入均 default-deny，必须解析到明确目标并匹配对应 fs.read/fs.write 范围；fs.read 不授予修改，fs.write 包含读取。deny 优先，凭据路径检查不能被目录 allow 绕过。网络按主机与端口精确匹配，不能丢弃端口或把含路径规则降低为整主机权限。未知资源拒绝；普通 warn/audit_only 仍只建议拒绝。原签名事实不改写，旧授权缺范围时需重新起草并人批，不自动扩大兼容范围。此修正及可信 Skill 归属缺口见 ADR-025。

`POST /v1/grants/{id}/resources` 按 `grant-resource-edit/v1` 编辑待批准授权，完整列表明确替换，空数组清空，精确 revision 与审计后发布；文件 deny、凭据/进程保护和保留工具的人批条件不因编辑丢失。工具 deny 优先于 allow/hold。界面与兼容语义见 ADR-026，不把编辑成功显示为已生效或可信 Skill 归属。

### 会话固定授权选择（ADR-027）

`POST /v1/intent-bindings` 的 `intent-grant-bind/v1` 管理请求明确 Grant ID 和其预览版本，生成含 grant_ref 的签名绑定。每次解析验证所选 Grant，失效不回退其他授权；旧无 grant_ref 绑定保持兼容。绑定选择不由决定请求携带，具体摘要、期限、降级和可信 Skill 归属边界见 ADR-027。普通 Grant 策略仍保留模式语义；被固定的授权选择失效属于 Authority 错误。

### 个人实例身份与自动接入（ADR-028，实施中）

管理接口 `/v1/runtime-identities` 发行/查询实例身份，`/{id}/revoke` 追加撤销；`POST /v1/runtime-sessions` 只接受实例凭据，为真实宿主 session 自动创建固定 Grant 的权限包络。凭据元数据和撤销记录签名追加，秘密文件独立保存，不从 HTTP 返回。保留 `hri-` 主体用于实例身份，`rca-` 用于自检短期凭据；全局决策凭据不能冒用。管理状态不提升为接入成功，具体期限、旧配置兼容、JSON 身份字段、重启与原生验证边界见 ADR-028。

ADR-028 核心存储约束：实例记录最多 512 项、单条 16 KiB；`runtime-identities/<ri>.json` 为签名发行记录，`runtime-identity-revocations/<ri>.json` 为签名终止记录，`runtime-identity-secrets/<ri>.token` 单独存客户端凭据。目录 0700、文件 0600；标准库完整写入、fsync 后独占链接发布，禁止覆盖。认证每次重读发行/撤销/Grant；拒绝软链接祖先、字段别名、重复键、缺省/null 替代和不安全权限（Windows 权限由后续原生交付验证）。崩溃遗留的秘密文件没有签名发行记录时不产生认证能力。全进程写互斥配合既有 daemon state writer 锁，不宣称防御同 UID 竞态。

自动会话核心按 identity ID 与原生 session ID 派生稳定 Intent/task ID；权限包络复用 Grant 工具允许/人批集合并保留 deny 优先，列举已知效果但不允许 unknown，具体资源与条件仍由所选 Grant 裁决。首次签发与绑定分步追加，中断后只复用完全匹配且未过期的原包络；重试不延长期限，撤销或新身份不能重新接管旧会话。此处核心包实现不等于 HTTP 路由、适配器、安装事务或 UI 已接通；须由后续证据分别确认。

ADR-028 HTTP 接入增量：`GET/POST /v1/runtime-identities` 仅管理会话访问，发行返回脱敏身份摘要和客户端凭据路径（不读回秘密），查询返回 issued/revoked/grant_unavailable，runtime_state 始终 unverified。`POST /v1/runtime-identities/{ri}/revoke` 要求版本和操作者。`POST /v1/runtime-sessions` 只接受实例凭据和真实 session_id；派生身份由服务端输出。新增请求严格拒绝缺省、null、重复/未知字段、大小写别名及超过 16 KiB 正文。既有六类决策端点在解析平台/主体/会话后验证凭据范围；身份字段大小写别名或重复拒绝。全局决策凭据保留旧主体兼容，但不得访问 hri-/rca- 保留主体。运行自检的短期启动凭据只认证活动检查已绑定的真实 session；失效即拒绝，不能代替普通实例或管理权限。

### 已管理实例安装整合（ADR-029，实施中）

接入预览支持 runtime_identity_id，响应 `local-adapter-plan/v3` 绑定该身份；凭据引用由本地服务派生。修复不能降级到全局凭据；安装计划固定身份元数据与未撤销状态，应用时重查身份/Grant。归属记录保存引用，自检/诊断识别该配置。已管理实例卸载先追加身份撤销，再执行文件事务，失败不复活凭据；恢复只恢复文件，不恢复权限。具体兼容、确认与验证边界见 ADR-029。

### 权限修订草稿（ADR-030，实施中）

`POST /v1/grants/{id}/draft` 通过 `grant-draft-create/v1` 在精确源版本下创建独立待批准授权与策略；保留范围/拒绝/人批条件/期限，清除批准与生效证明。客户端请求标识绑定源版本和操作者提供幂等读回；源检查与新草稿发布使用同一 state commit 锁，审计失败不显示可用。响应 `grant-draft-created/v1`。实例换发先准备并人工批准新草稿，再明确撤销旧身份、发行新身份和确认配置；失败不复活旧权限，原会话不能被新身份接管。具体边界见 ADR-030。

ADR-030 准入存储修正：禁止在签名后补写 skill_card_ref；卡片按既有同名文件位置保存。旧记录只允许识别精确的本机派生卡片路径，再将此非授权字段还原为原 null 验证原签名，其余字段不可忽略，历史不改写。通用 admission.Verify 保持严格。源准入无法验证或 quarantine 时不得新建修订草稿。

### 个人统一确认待办增量（2026-09-10，ADR-031）

按 ADR-031 与 `local-confirmations.v1` / `local-confirmation-resolve.v1` 合同新增管理会话专属列表和严格摘要绑定的单次处理入口。列表是既有 action 窗口内的状态投影，不能批准；处理须锁内检查未处理、签名回执摘要和参数摘要，一次性写入 hold_resolution。截止时刻拒绝；客户端收到冲突后读回，不自动重放。旧 hold API 的幂等不产生新增审批权限。前端统一运行确认和长期授权的审阅入口，保留平台继续执行能力限制，不宣称系统通知或 Hermes 自动恢复已完成。

### 个人浏览器通知增量（2026-09-10，ADR-032）

复用 `/v1/confirmations` 与 `/v1/grants` 只读管理合同，合并个人外壳的待办刷新、导航计数及通知。通知默认关闭、人工开启；同源 Web Locks 协调、请求 ID 摘要去重、500ms 合并与 15 秒限流。Notification 点击只定位待办，不修改授权。状态目录和签名回执无新增通知原文。浏览器生命周期内的提醒不代替后台启动器；Hermes 缺少最终参数执行前复核的原生接入维持阻断。

### Skill 固定导入副本（2026-09-10，ADR-033）

按 `local-skill-import-create.v1` 和 `local-skill-import.v1` 新增共用导入存储核心。所有来源最终在状态目录形成有完整文件/目录/执行位清单的副本，仅在副本上准入；签名导入记录最后排他发布，绑定载荷与分析摘要。`.git` 不复制；拒绝链接、危险路径及超限内容；任何后续使用必须重新读回验签和比对全部载荷。既有 admission.content_hash 继续原有规则，不能替代完整 artifact_digest。本地目录/ZIP 是首批获取方式，后续 HTTPS/Git、产品 API/UI、权限批准和平台安装事务仍属于完整 UX-009 目标。

ADR-033 管理入口：`POST /v1/skill-imports` 与 `GET /v1/skill-imports/{id}` 使用管理会话和 `local-skill-import-result.v1`；前者首次 201、同 ID 重试 200，后者完整副本校验后 200。固定大小写必需请求字段、绝对本机来源路径、16 KiB 正文；单并发、60 秒请求期限，繁忙 429，取消/期限 408，内容变化或冲突 409，超限 413。返回不代表批准或安装，错误不暴露路径或原文，具体审计、重试与边界见 ADR-033。

### Skill 导入记录与个人审阅（ADR-034）

新增管理 GET `/v1/skill-imports` 和 `local-skill-import-list.v1`：最多 64 条，读取签名元数据及清单摘要，payload_status 固定 unchecked；单条损坏仅返回 ID 与 unavailable，详情仍需完整内容复核。记录目录最多 128 条目；不发布暂存内容。个人 `/skill-imports?import=si-…` 页面使用随机请求 ID、原请求重试、历史查询及不可信文本展示，不自动批准、安装或重试写入。前端仅导入相关调用使用 70 秒预算，并支持离开页面取消；其余细节及验收边界见 ADR-034。

ADR-034 准入显示修正：固定导入使用不透明 source.locator，内部 SourceIsOpaque 标识跳过目录名信息比较，保留名称格式、正文威胁与其他检查；默认路径来源行为和历史签名不变。

### HTTPS Skill ZIP 获取（ADR-035）

管理 POST `/v1/skill-imports/remote` 接受 remote-create/v1 的 URL、归档目录、预期 SHA256 和操作者，下载后复用固定副本/准入流程。只允许公网 HTTPS/443、每跳 DNS 校验与 IP 固定，禁代理/凭据/Referer，最多三次重定向、45 秒、32 MiB；路径和解包预算继续按 ADR-033。记录和结果 v2 绑定归档摘要/字节数/目录及最终 URL 摘要，不保存 URL；本地 v1 签名和结果不变，混合历史用 list/v2。CLI 和前端都只保存候选，不产生批准或安装，具体边界与兼容见 ADR-035。

### 固定导入候选的权限准备（ADR-036，M20）

以 local-skill-import-permission-source/v1 的完整导入身份派生独立 admission，source.ref 保存规范化来源对象，adm-si- 全 SHA256 ID 经 Grant 签名与批准挑战绑定。原始扫描记录不回写；派生 admission 使用严格同值持久化。权限草稿使用独立 grt-si- 请求身份，仍复用原 Grant/CAS/人工批准与审计，不自动授权或安装。当前核心拒绝导入权限进入 deployed/effective，后续必须以安装事务和实际目标内容读回证据完成转换；具体阶段、API 计划及兼容限制见 ADR-036。

### 安装预览的私有暂存（ADR-037，实施中）

新 skillinstall 模块在状态目录形成已批准候选的独立待安装副本和签名计划，绑定 ADR-036 来源、Grant revision/签名/权限摘要、实际 Hermes 实例和单层目标目录。仅规划尚不存在的目标，目标目录不写入；五分钟期限、同请求不续期、64 个暂存上限，Load 必须重新验证源/授权/目标/副本。沿用固定导入的完整文件清单与预算，不使用旧 admission.content_hash 代替。合同 local-skill-install-stage-create/v1、local-skill-install-plan/v1；目标发布与恢复、安装后保护验证继续实施，不解除 M20 的部署限制。

### 安装预览的管理入口（ADR-038，实施中）

管理 POST `/v1/skill-installations/plans` 严格接收 stage-create/v1，返回 plan-created/v1；管理 GET `/v1/skill-installations/plans/{id}` 完整复验后返回 plan/v1。与导入共享单并发工作锁及 60/65 秒处理/写出预算，决策凭据不能访问。目标只由 Hermes 实例解析器解析。签发页从已批准的来源绑定授权进入，响应丢失保留原请求，刷新只按计划 ID 复验；生成预览不安装、不部署、不激活运行身份。

### Skill 文件发布与恢复（ADR-039，实施中）

实际安装须绑定明确确认的计划签名，重新校验当前批准权限、候选与暂存；独占创建目标，逐文件排他发布，完成状态以目标完整读回为依据。平台目标不使用无条件覆盖或 RemoveAll。归属不明、用户修改或恢复不完整须保留并报告，不能假装已回滚。目录创建与归属记录之间的崩溃窗口不得通过猜测归属来清理。

skillimport 的 InstallationSnapshot 为安装器提供只读固定清单句柄：打开时完整校验，逐文件按固定清单检查类型/摘要/大小/执行位，Metadata 返回独立副本，批次结束 Verify 完整复验来源签名与分析。该接口不写外部路径、不执行内容、不授予权限；具体安装提交/恢复合同与实现继续按 ADR-039 推进。

安装提交 apply/v1 绑定计划 ID/签名、同一操作者及显式 confirm_install=true。claim/v1 在任何 profile 写入前排他落盘，绑定计划与完整清单；operation/v1 分别记录 installed_unverified/rolled_back/recovery_required，runtime_verified 始终 false。owner/v1 的签名与硬链接文件身份用于目录归属；同一计划不重复提交。成功结果需当前完整目标读回；恢复可独立于当前授权/候选执行，但不能删除未知或修改过的对象。首个结果与后续恢复记录均不可变，不通过恢复激活权限。具体目录、保留名称及跨进程崩溃窗口见 ADR-039。

### 安装确认与恢复管理入口（ADR-040）

管理 POST `/v1/skill-installations/apply` 接受 apply/v1；GET `/v1/skill-installations/operations/{sin-id}` 返回 view/v1；POST 同一路径 `/recover` 接受 recover/v1（schema_version、actor_id、confirm_recovery=true）。均管理会话限定、no-store、共享导入互斥及 60/65 秒预算。成功处理返回 200 view/v1，实际安装结果由 status 区分，失败已回滚不能解释为安装成功；没有可验证操作证据时返回固定错误类别。view 包含已验签 claim 的计划和签名摘要，不返回完整文件清单；无最终记录时 operation=null、status=recovery_required，禁止伪造已签名结果。已安装状态必须当前完整目标读回；已回滚是历史记录。恢复无当前 Grant/候选依赖，不得借此卸载成功安装。

前端明确勾选确认并提交，提交前保留确定性的 sin-id，响应丢失/刷新只查询，不自动重放写入。尚无操作记录时可显式回到原计划重新核验确认。结果及恢复界面独立于授权是否仍批准、候选是否可读；错误时撤下旧成功状态。恢复需单独明确确认，只处理归属可证且未被修改的失败安装对象。保护状态不提升，导入授权的 deployed/effective 限制保持。

### 安装内容绑定的实例权限准备（ADR-041）

导入 Grant 的通用 deploy/effective 入口仍拒绝。仅安装器的 activate/v1 操作可在完整安装读回、原批准版本/签名/权限、源候选和实例一致时准备实例权限：先排他发布 runtime-binding/v1，再以现有 GrantCommit/CAS/审计追加相同批准内容的新版本，状态保留 approved。该操作不签发运行身份、不修改适配器、不代表宿主保护或可信 Skill 调用归属；需要显式 confirm_instance_scope=true，表示所选权限约束实例会话。管理 POST `/v1/skill-installations/operations/{sin-id}/activate` 返回 activated/v1，重复请求只读回原绑定，不重新授权或延长期限。计划的安装预览期限只限制安装提交，不限制已安装对象的后续人工权限准备；Grant 本身期限始终验证。

状态目录 `skill-installations/runtime-bindings/sab-<sha256(grant_id)>.json` 保存签名安装/授权绑定，包含原计划与操作签名、原批准版本与签名、权限摘要、来源、实例、操作者和时间。每个 Grant 只能绑定一次安装。绑定落盘但对应批准版本未提交时无运行权限；审计/提交失败保持不可用，沿用已有状态提交恢复。准备后的读回和运行验证均检查目标完整内容、原候选与来源准入、当前批准权限摘要、签名和期限。

state.IntentAuthority 的 Grant 读取对导入来源默认拒绝；只有 daemon 注册的完整安装验证器成功才可选择/使用。未配置验证器的离线读取不能启用导入权限。实例凭据发行、认证、会话登记、固定绑定决策和既有审批复核都通过该读取路径重新验证，不缓存成功结论。未选择固定 Grant 的旧隐式路径不得使用导入 Grant，所有模式拒绝该 Authority 缺口。普通非导入授权保持既有行为。此处文件完整性检查不宣称防御恶意同 UID 或宿主执行前竞态，不将模型自报 Skill ID 升级为可信归属。


ADR-041 兼容边界：安装绑定不把旧格式 Grant 标成 deployed/effective。相同的已批准内容经 CAS/审计追加一个新版本，runtime-binding 的 approved_revision+1 必须与当前版本精确相同。只有注册内容验证器的固定 Grant 读取路径承认该批准版本可供实例会话使用；旧二进制的固定选择和隐式查找都拒绝 approved，因此不能因读到新安装权限而绕过内容绑定。旧版行为实测与新版本运行测试分开登记。通用部署/effective 仍拒绝；前端后续按绑定结果显示“实例权限已准备”，不能把普通 approved 当作已运行保护。


ADR-041 校验预算：所有运行内容复核共用单并发槽，服务端每次验证的排队与读取总预算为五秒；过期/取消时拒绝，成功结果不缓存。普通 Intent.Open 默认不接纳 approved 导入 Grant，只有 state 的显式安装验证读取入口可以；该入口在未注册安装验证器时仍默认拒绝。隐式 Grant fallback 遇到导入权限属于 Authority 缺口，不能在 warn/audit_only 下放行，普通非导入模式保持原语义。

### 安装权限只读准备状态（ADR-042）

安装结果与管理实例界面使用管理 GET `/v1/skill-installations/operations/{sin-id}/runtime` 和 `/v1/skill-installations/grants/{grant-id}/runtime`，输出 `local-skill-install-runtime-readiness/v1`。后者仅从已验签安装绑定解析，不扫描或猜测安装目标。前者完整验证目标、导入来源、批准内容和期限；状态 not_prepared（无绑定、原批准版本）、incomplete（已发布绑定、仍为原批准版本）、prepared（绑定完整、当前版本为原批准版本+1），仅允许精确对应的签名和版本。返回完整签名 Grant、当前 state_revision 和可选绑定；不修改任何权限状态。空可运行工具集显示 no_tools，activate 与身份发行在任何绑定/凭据发布前拒绝，旧空工具绑定不能用于运行。查询沿用管理分权、no-store、安装工作锁和时间预算。刷新只 GET，恢复写操作必须明确确认；prepared 不等同运行验证或 Skill 归属证明。

### 已安装 Skill 的历史记录与内容检查（ADR-043）

管理 GET `/v1/skill-installations/operations` 以 catalog/v1 返回至多 64 份已验签 record/v1，包含计划、声明签名和历史结果，recorded_status 不表示当前目标/权限状态。损坏项只报告不含未验证正文的 issue；状态目录超过 256 项显式拒绝。GET `/v1/skill-installations/operations/{id}/inspection` 按原签名清单检查当前目标，输出 inspection/v1 的 matched/changed/missing/unavailable、检查时间、完成标志及变化条目。未知目录不递归、未知文件不读取；只读取原清单中的普通文件并检查大小、执行位、摘要与归属，不执行或修改目标。观察目录项总预算 8192，原清单内容最多 64 MiB，单文件 8 MiB，返回最多 200 条变化，截断明确标注；读取失败/取消/预算不足不能返回 matched。列表和检查均不恢复操作或启用权限；原 ReadView/运行校验的拒绝规则保持。个人界面提供记录入口、按安装选择的检查和原操作跳转；可见页面每 30 秒更新所选检查，隐藏时停止请求。检查只针对安装基线，不声称远端新版检查、更新或卸载已实现。

### 明确移除与恢复（ADR-044）

`remove/v1` 绑定成功安装的 operation_signature、expected_grant_revision、expected_binding_signature（无绑定为空串）、actor_id 和 confirm_remove=true。管理 GET/POST `/v1/skill-installations/operations/{sin-id}/removal` 分别查询/执行；复用管理权限、安装工作锁、取消和时间预算。移除声明先以 removal-claim/v1 签名发布到 `skill-installations/removals/{sin-id}.claim.json`，只有原确认内容可继续重试。待撤销 Grant 和目标不得重新 Activate；运行验证器拒绝已开始移除的目标。

当前 Grant 必须签名有效并与原安装的主体、来源和权限摘要一致。其运行绑定属于另一安装时保留 Grant，并固定该绑定；否则经既有 GrantCommit/CAS/审计撤销，确认完整撤销后才清理外部目标。源内容损坏/过期不阻止撤销，不影响其他实例或目标。清理复用完整归属预检，未知/修改对象保留并进入 cleanup_pending。Grant 处理尚未完成为 revocation_pending。只在目标缺失且权限处理已完成时签名追加 removal-result/v1；已完成请求重试只读历史结果，不清理后来出现的新目录。

查询 removal-view/v1 返回原签名历史记录、可选声明/结果及当前 Grant/版本（完成终态可为空）。无声明为 not_requested，已有声明且尚未撤销为 revocation_pending，权限处理完成但未有最终结果为 cleanup_pending，结果存在为 removed。不能读取/校验当前权限时返回错误，不能把未知状态解释为完成。移除记录只追加，枚举至多 256 项。目录标记删除与 rmdir 之间崩溃留下归属不明空目录时保留，不自动猜测删除；用户核对处理后重试。该路径不代表自动更新、完整共享资源清理或通用旧状态写入防护已实现。

### 个人移除确认与恢复窗口（ADR-044，M30）

已安装 Skill 页顺序读取 removal-view 与 inspection；历史 removed 单独显示。确认窗口冻结安装选择及背景检查，展示文件目标与 Grant 撤销/保留范围。所有写入须明确勾选与点击，原声明重试固定签名/版本/操作者。响应丢失只读查询，未知状态撤下执行按钮；恢复继续明确确认，完成后只保留历史结果。客户端校验合同及记录关联，不据 UI 校验宣称密码学验签。关闭窗口不代表服务端取消。

### Skill 更新候选比较（ADR-045）

新增 `local-skill-update-compare/v1` 请求和 `local-skill-update-comparison/v1` 响应，管理 POST `/v1/skill-installations/operations/{sin-id}/update-comparison` 只读比较原签名安装清单与绑定新 Grant 的完整导入候选。固定原 operation_signature 与新 Grant 版本，验签、校验实例/平台/准入/来源与期限；原 Grant 权限摘要须仍匹配原安装。新候选允许未批准以支持批准前审阅，不因此生效。结束复验双方 Grant 版本/签名及移除状态。

内容和规则差异各最多返回 200 项并记录完整总数/截断状态；规则忽略 ID/证据来源但保留条件、资源与状态，另比较默认效果、执行模式、期限和工具策略。不推断权限扩大或缩小。比较不检查现存目标、不执行内容、不写状态或平台文件，也不批准或续权。响应始终要求后续明确确认，不宣称版本已切换；现存目标完整性、更新提交/恢复与远端检查另行实施。

### 保留旧版本的更新准备（ADR-046）

新增 local-skill-update-stage-create/v1、local-skill-update-plan/v1、local-skill-update-plan-created/v1。创建请求固定原操作签名、两份 Grant 版本、原运行绑定签名、操作者和 up-request ID。只接受已批准的新 Grant；旧目标完整归属检查、新来源和新暂存副本检查通过后，才签名排他发布 5 分钟计划。状态与副本分别置于 update-plans 和 update-stages，普通安装接口不可消费。相同请求复用而不续期，输入变化拒绝；64 份暂存、128 项计划枚举上限，中断孤立副本不隐式接管。

POST /v1/skill-installations/operations/{id}/update-plans 创建，GET /v1/skill-installations/update-plans/{id} 重新核验。全过程不变更原目标、权限或身份，plan 标记 platform_changes=false、runtime_verified=false、requires_confirmation=true。确认切换、事务恢复和产品界面在后续批次接通。

### 明确确认的更新事务（ADR-047）

新增 update-commit/v1、update-recover/v1、update-claim/v1、update-result/v1、update-view/v1。更新声明固定原签名更新计划和同期限的新安装计划，排他保存到 skill-installations/update-operations；新普通计划仅在原移除完成后发布。先验证新副本，再按原范围撤旧权限/清理旧目标，最后复用排他安装。继续不续期；已成功安装的历史结果可在过期后补记更新结果。恢复须明确确认声明签名，未开始移除可终止且保留旧版本，已开始则完成撤权/清理；失败新安装仅做归属可证的清理，不复活权限或自动重装。查询不写入，终态为历史结果，不代表当前运行保护。核心先实施，HTTP 与前端接入另行登记。

ADR-047 管理入口：POST /v1/skill-installations/updates 提交 update-commit/v1；GET /v1/skill-installations/updates/{sup-id} 读取 update-view/v1；POST 同一路径 /recover 接收 update-recover/v1，正文 update_id 必须与路径一致。只允许管理会话，严格字段/正文、no-store、共享安装互斥及 60/65 秒预算。写入发生错误时返回稳定错误类别，客户端只能先 GET 查询持久进度，不消费错误前的状态快照、不自动重放。成功返回 200 的实际结果仍以 status 区分；不因 API 可用而宣称前端或原生平台更新验收完成。

### 个人更新差异与恢复页面（ADR-047，M34）

个人版从已安装记录进入 /skill-updates，固定 install_id；候选列表限同平台/实例的独立导入授权。比较展示原签名安装基线与新候选的内容、规则和设置差异，未批准候选仅可审阅，准备前须人工批准并重新比较。准备明确固定当前移除范围及原比较签名，更新操作以 update_id 深链保存；刷新先 GET 查询事务，尚无事务才 GET 复验计划，不自动写入或重新批准。计划刷新后须人工重新比较才可勾选首次更新确认。

新页面对比较、计划、事务及请求范围做字段和关系检查，不把客户端形状检查称为密码学验签。确认提交使用原计划签名与操作者；已开始事务继续使用原声明，恢复另需明确勾选。写响应丢失先 GET 查询，查询失败清空可执行状态并保留原操作链接，绝不自动重发 POST。更新成功只显示新版文件发布的历史记录，并引导单独准备实例权限；终止不代表旧版本仍可运行，按实际移除证据说明。跨系统通知、远端新版轮询及真实平台支持声明不随本页面提升。
