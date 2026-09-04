# AgentShield · Skill 门禁官 — 设计方案 v1

- 日期：2026-09-04
- 依据：ADR-011；`docs/research/agentshield-market-survey-2026-09.md`；ADR-003/004/005
- 目标赛事：第三届 NVIDIA DGX Spark 黑客松 · Agent Skills 开发挑战赛（报名截止 9/19，提交 9/20–29，决赛 10/15）

## 1. 一句话

在任意支持 Agent Skills 的平台上装一个 Skill，本机就多出一个「门禁官」：盘点 Agent 资产、审查来源不明的 Skill、按声明签发最小权限、把 Agent 关进 OpenShell、给每次工具调用开签名回执，越权当场拦截。

## 2. 目标与非目标

**目标**

1. 一份 `SKILL.md` 在 OpenClaw、Hermes、WorkBuddy、Trae 上可安装可运行。
2. 一个 Go 单文件二进制覆盖 Linux / macOS / Windows，内嵌 Web 控制台。
3. 拦截能力按平台真实钩子分档（L0–L3），控制台如实显示当前档位。
4. 所有裁决来自二进制与规则包，模型输出永不成为 `effective`。
5. Linux 上完整跑通红蓝对抗演示；macOS 演示二进制跨平台。

**非目标**

- 不做通用 MCP 代理、不做 HTTPS MITM、不做企业 NHI/IdP。
- 不 Fork OpenShell，不另起沙箱（E2B/gVisor）。
- 不在 v1 实现 Python AST 检测层、OMS/Sigstore 签名、SkillEvaluator T3 评测。
- 不承诺 Windows 上的 L3；不承诺 Trae 上的阻断。

## 3. 架构

```
┌──────────────────────── 用户主机（任意 OS）────────────────────────┐
│                                                                    │
│  Agent 平台（OpenClaw / Hermes / WorkBuddy / Trae）                │
│   ├─ skills/agentshield/SKILL.md   ← 入口：校验二进制、注册适配器   │
│   └─ 平台钩子 ──► 适配器（薄）──► http://127.0.0.1:<port>/v1/decide │
│                                                                    │
│  agentshield（Go 单文件，内嵌 Web）                                 │
│   ├─ inventory  盘点（复用 connectors/*）                            │
│   ├─ admission  准入（规则包 + frontmatter + 哈希 + Skill Card）      │
│   ├─ grant      五态权限事实 → Hermes/OpenClaw allowlist + DesiredPolicy │
│   ├─ receipt    决策 API + 污点 + 哈希链回执 + Ed25519               │
│   ├─ openshell  网络策略 policy set / 读回（Linux 或 Docker）         │
│   └─ ui         控制台（apps/web 构建产物 embed）                    │
│                                                                    │
│  状态目录（本地模式）：state.json / facts/ / policies/ / receipts/*.jsonl │
│  可选同步 ──► Control API（现有 Edge 协议）                          │
└────────────────────────────────────────────────────────────────────┘
```

**信任链**：SKILL.md → 校验二进制哈希（写在 SKILL.md 与 release manifest）→ 二进制校验规则包 Ed25519 签名 → 适配器只接受 localhost + 本地 token → 回执由二进制签名，模型与适配器都无签名密钥。

## 4. 四个子 Skill 与二进制子命令

| 子 Skill | 子命令 | 输入 | 输出 | 复用 |
| --- | --- | --- | --- | --- |
| agent-asset-inventory | `agentshield inventory` | 平台配置目录（只读，不启动 MCP） | candidate + evidence + declared 事实 | `connectors/{hermes,openclaw,workbuddy,mcp,directory}`；**新增**：扫 `skills/` 目录 |
| skill-admission | `agentshield admit <path\|zip\|git>` | Skill 目录 | `admission.json`（verdict / declared 能力 / findings / hash）+ `skill-card.md` | 规则包（Go 移植）、`/tmp/agentshield-backup` 的决策表与 evals |
| least-privilege-grant | `agentshield grant <admission.json>` | declared 事实 + 用户签核 | Hermes toolset allowlist、OpenClaw tool policy、OpenShell `DesiredPolicy`、`effective` 读回 | `policy_compiler`（Go 移植）、permission-fact schema |
| runtime-receipt | `agentshield serve` + `/v1/decide` | 钩子转发的工具调用 | allow / deny / hold / redact + 签名回执 | Hermes `pre_tool_call`、OpenClaw `before_tool_call`、CodeBuddy `PreToolUse` |

### 4.1 准入决策表（对标 SkillEvaluator triage）

| 发现 | 处置 |
| --- | --- |
| 欺骗用户、隐藏指令、提示注入、Unicode 同形/零宽、HTML 注释指令 | **quarantine**（硬隔离） |
| 读取凭据路径并在同一 Skill 内出现外传槽（curl/requests/fetch → 非白名单域） | **quarantine** |
| 完整性失败（哈希不匹配、符号链接逃逸、超体积、二进制混入） | **quarantine** |
| `allowed-tools`、sudo、包安装、出网域名、写路径、模型调用 | **admit_with_conditions** → 产出 `declared` 权限事实交 grant |
| 无以上任一 | **admit** |

官方 NVIDIA 349 个 Skill 作为负向回归集：隔离率必须显著低于备份实现的 10.6%，且 84 个使用 `allowed-tools` 的 Skill 不得因该字段被隔离。

### 4.2 决策 API

```
POST /v1/decide
{ "platform":"openclaw", "session":"...", "tool":"exec", "params":{...}, "agent_id":"..." }
→ { "action":"allow|deny|hold|redact", "reason":"...", "receipt_id":"...", "params":{...} }
```

- 预算：OpenClaw 钩子 15s fail-closed，本 API 目标 p95 < 200ms。
- 污点：session 内一旦参数或结果命中脱敏规则（secret/PII），后续出网类工具默认 `deny`；实现 lethal trifecta 最小版（私有挂载读取 ∩ 不可信 Skill 已加载 ∩ 出网）。
- `hold` 需用户在控制台或平台 approval 流中签核；OpenClaw 映射为 `requireApproval`。
- 每条决策写回执：`prev_hash`、`hash`、`sig`、工具、参数摘要（脱敏）、命中的 grant/事实、`policy_revision`、`sandbox_id`、模型 key。

### 4.3 平台适配器

| 平台 | 安装门禁 | 运行时 | 卸载 |
| --- | --- | --- | --- |
| OpenClaw | `security.installPolicy.exec` 指向 `agentshield policy-exec`（stdin JSON → allow/warn/block） | 插件 `before_tool_call` → `/v1/decide`；`after_tool_call` 上报结果 | 删插件 + 还原 `openclaw.json` |
| Hermes | 包装 `hermes skills install`：先 `admit` 再放行；本地放入目录由 inventory 周期扫描 | 插件 `pre_tool_call` / `post_tool_call` | 删 `~/.hermes/plugins/agentshield` |
| WorkBuddy/CodeBuddy | 无；SKILL.md 引导「先扫再装」 | 写 `~/.codebuddy/settings.json` `PreToolUse` 钩子脚本（需用户确认） | 移除该条钩子 |
| Trae/TraeWork | 无 | 无；控制台标「审计模式」 | 删 Skill |

### 4.4 OpenShell（L3）

- 只做：网络策略 `policy set` + `policy get --full` 读回 revision → `effective`；模型路由（本地 Nemotron 放行，云端 StepFun 经脱敏 broker）。
- 文件系统/进程策略在沙箱**创建时**静态写入；不调用 `create_generation`，不把 fs 策略装成已热部署。
- 能力探测优先于版本假设（ADR-005）；macOS/Windows 无 Docker 时 L3 显示「不可用」。

## 5. 目录布局（本仓）

```
skills/agentshield/                 SKILL.md · scripts/bootstrap.{sh,ps1} · references/ · evals/ · skill-card.md
apps/agentshield/                   Go module
  cmd/agentshield/                  main：serve / inventory / admit / grant / policy-exec / verify
  internal/rulepack/                规则包加载 + Ed25519 验签（对齐 app/rulepack.py）
  internal/admission/               frontmatter、哈希、决策表、Skill Card
  internal/grant/                   permission-fact → allowlist + DesiredPolicy（policy_compiler 移植）
  internal/receipt/                 决策、污点、哈希链、签名
  internal/openshell/               CLI 后端（policy set / get）
  internal/ui/                      embed apps/web/dist
  testdata/                         与 Python 共用的语料（软链或复制自 control-api fixtures）
adapters/runtime/openclaw-agentshield/   TS 插件 + installPolicy 说明
adapters/runtime/hermes-agentshield/     Python 插件（薄，只做 HTTP）
adapters/runtime/codebuddy-agentshield/  PreToolUse 钩子脚本
packages/contracts/                 新增 admission / grant / receipt / manifest schema（升版本）
```

`connectors/*` 各自是独立 Go module，`apps/agentshield` 通过 `go.work` 或 replace 引入；协议类型仍只经 `edge/agent/protocol`。

## 6. 合同变更（W0，先于实现）

| 新 schema | 关键字段 |
| --- | --- |
| `admission.schema.json` | `skill_id`、`content_hash`、`verdict`（admit / admit_with_conditions / quarantine）、`declared_facts[]`（permission-fact）、`findings[]`、`evidence_ids[]` |
| `grant.schema.json` | `subject`、`facts[]`（五态）、`hermes_allowlist[]`、`openclaw_policy`、`desired_policy`、`overlap_conflicts[]`、`approved_by`、`effective_readback` |
| `receipt.schema.json` | `receipt_id`、`prev_hash`、`hash`、`sig`、`platform`、`tool`、`params_digest`、`action`、`matched_facts[]`、`taint_labels[]`、`policy_revision` |
| `skill-manifest.schema.json` | 二进制版本、哈希、规则包版本、支持平台 × OS × 档位 |

变更规则不变：先升 schema，再改 Go 与 Python 两侧，示例即测试夹具。

## 7. 演示脚本（3 分钟）

1. 财务分析 Agent（仓内合成 Hermes/OpenClaw profile）装了一个来源不明的「报表美化」Skill；无 AgentShield 时它读取 `.env` 并 POST 到外网——红队成功。
2. 装 AgentShield Skill：模型校验二进制、注册适配器，控制台亮起「本地模式 · L3」。
3. `admit` 该 Skill：隔离，红卡列出隐藏指令与凭据外传证据；再 `admit` 一个 NVIDIA 官方 Skill：admit_with_conditions，列出 `allowed-tools` 与出网域名。
4. `grant`：人工签核，生成 allowlist + 网络策略，`policy set` 读回 revision → `effective`。
5. 沙箱内运行；Skill 试图越权访问兄弟目录/未授权域 → `deny`，红色签名回执弹出，`agentshield verify` 验签通过。
6. 切到 macOS：同一二进制跑 inventory + admit，L3 显示「需 Docker」。

## 8. 工作拆分

| 阶段 | 内容 | 验收 |
| --- | --- | --- |
| W0 合同 | 四份 schema + 示例；`docs/compatibility.md` 加平台 × OS × 档位矩阵 | `test_schema_contracts` 通过 |
| W1 Go 核心 | rulepack（42 条直移 + crontab 改写 + dangerous-import 正则）、signing、admission、grant | Go 与 Python 对同一语料输出一致；官方 349 Skill 回归 |
| W2 二进制与 UI | `serve` / `/v1/decide` / 哈希链回执 / embed 控制台；三 OS 交叉编译 | Linux/macOS/Windows 各跑 inventory + admit |
| W3 适配器 | OpenClaw 插件 + installPolicy；Hermes 插件；CodeBuddy 钩子 | 每平台一次「越权被拒」E2E |
| W4 OpenShell | 网络策略下发 + 读回；模型路由 | `effective` 读回；静态 fs 不伪装 |
| W5 Skill 包 | SKILL.md（≤60 字符 description）、bootstrap、evals、Skill Card、release zip + manifest | 四平台安装成功；Trae 显示审计模式 |
| W6 材料 | README、演示脚本、检测基线更新、十日谈 | 评委可离线复现 |

## 9. 验证

- Go：`go vet ./... && go test ./...`；一致性测试读取 `apps/control-api/app/tests/fixtures/threat/corpus.json`。
- Python：`uv run pytest`（不回退）。
- 合同：schema 示例校验 + 双实现字段同步。
- 负向：恶意 Skill 语料（隐藏指令、Unicode、外传、符号链接、超体积）必须 quarantine；官方 Skill 集不得被误隔离；`/v1/decide` 超时必须 fail-closed（block 模式）。
- 平台：每平台一条「装 → 扫 → 授 → 拦」E2E 录屏。

## 10. 风险与对策

| 风险 | 对策 |
| --- | --- |
| 无钩子平台的虚假安全感 | 控制台与 Skill Card 显式标档位；Trae 只标「审计」 |
| Go/Python 双实现漂移 | 共用规则包 + 共用语料 + 一致性测试进 CI |
| AST 层缺席降低 Python 检测 | 正则层已覆盖 3/4 并补 1 条；基线文档如实标注 |
| 写用户全局配置（WorkBuddy） | 显式确认、幂等、可卸载 |
| Windows 语义（符号链接、路径、进程枚举） | 只承诺 L0–L2；connector 加 Windows 测试 |
| `create_generation` 不可用 | fs 策略静态创建，不承诺热更新 |
| Skill 本身被投毒 | SKILL.md 内置二进制哈希；release manifest 签名；自扫描 |

## 11. 与其他仓库的关系

只改 `siq-agent-security`。`hermes-agent`（siq-patches）与 `siq-research-engine` 仅作只读参考；被保护对象用仓内合成的最小 profile，不依赖 research-engine 数据。
