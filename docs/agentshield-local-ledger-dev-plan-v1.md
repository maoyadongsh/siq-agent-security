# AgentShield 开发计划：本地台账与企业能力对齐 v1

- 日期：2026-09-05
- 状态：**计划生效；P0–P3 已落地（2026-09-05）**。本文锁定目标、分期与不变量。新增 HTTP 路径、状态目录文件、UI 路由在开工该期之前回写 [`agentshield-dev-spec-v1.md`](./agentshield-dev-spec-v1.md)；未回写不得合入实现。
- 上游：ADR-011 → [`agentshield-design-v1.md`](./agentshield-design-v1.md) → [`agentshield-dev-spec-v1.md`](./agentshield-dev-spec-v1.md) → **本文（W7 增量计划）**
- 依据：仓内实现与证据（2026-09-05）、企业控制面 README / 控制台 IA、以及同期产品讨论（双入口、台账对参赛的价值、发现/管控能力边界）
- 赛事：第三届 NVIDIA DGX Spark 黑客松 · Agent Skills 开发挑战赛（提交 9/20–29，决赛 10/15）

> 一句话：评委复现仍是单文件门禁官；现场主界面要达到企业控制台那种「看得见、管得住、查得到」。Control API / PostgreSQL / 登录不是演示开关。

---

## 0. 本文解决什么问题

仓库里并存两条产品线，入口不同、观感不同、评委路径被写成只走其中一条：

| | 企业控制面 | AgentShield 本地门禁 |
| --- | --- | --- |
| 入口 | [`README.md`](../README.md)、`apps/web` 默认构建、`http://localhost:52741/agents`（本机 Vite 示例） | [`AGENTSHIELD.md`](../AGENTSHIELD.md)、`agentshield serve`、`http://127.0.0.1:47611` |
| 代码 | `apps/control-api` + `apps/web/src/{App,pages,components}` | `apps/agentshield` + `apps/web/src/local/` |
| 后端 | FastAPI `:8600` + PostgreSQL + 登录/多租户 + Edge | Go 标准库、文件态 `STATE_DIR`、loopback token |
| 回答的问题 | 公司里有多少智能体、谁批的、有没有漂移 | 这台机器上的 Skill 能不能装、这次调用允不允许 |
| 现场成本 | 库、身份、Compose | 一条二进制 |

讨论中已确认的张力：

1. 打开本仓默认跟评委路径，看到的是五页本地台，不是 `/agents` 那套台账。
2. 不借鉴企业栈，**发现与管控在本机闭环上已经成立**（Hermes Linux L0–L2 有证据），但盘点浅、权限五态没有对照面、看起来不像治理产品。
3. 「现场不需要企业控制面」说的是 **不需要 Postgres 进程**；**台账能力对参赛重要**，应成为本地控制台的主界面。
4. 不能把 FastAPI 焊进 `serve`，也不能让本地 UI 去调 `:8600` 当唯一事实源。

本文给出第三条路：**能力对齐、运行时不合并。**

---

## 1. 目标与成功标准

### 1.1 产品目标（不变）

与设计方案一致，本地门禁官仍是作品主体：

1. 一份 Skill 可安装；一个 Go 单文件覆盖 `linux/amd64`、`linux/arm64`、`darwin/arm64`、`windows/amd64`。
2. 裁决只由二进制与规则包产生；模型不能批准 grant、不能把扫描结论写成 `effective`。
3. 拦截按平台真实钩子分档（L0–L3）；无 OpenShell 时产品仍完整，顶栏写「仅工具层拦截」。
4. filesystem / process **永不**标 `effective`；OpenShell 只认已验明网关；不 `gateway start`、不改兄弟仓。

### 1.2 本计划增量目标（W7）

让 AgentShield **具备企业控制面那套治理语义**，数据与决策仍在本机：

| 企业台能力 | 本地等价物 | 成功时评委能看到 |
| --- | --- | --- |
| 智能体资产台账 | 本机资产列表 + 详情 + 证据 | 接近 `/agents` 的信息架构 |
| 候选确认 / 驳回 | 文件态资产状态机 | 影子 Skill 标红，确认后进入纳管 |
| 权限五态对照 | 聚合 declared / inferred / observed / effective | 一张表讲清「自称 ≠ 签发 ≠ 拦截 ≠ 沙箱读回」 |
| 五域编辑 | 在详情/签发里改工具与网络（fs/process 可声明、不热更新） | 人改完再批准，不是只能 CLI |
| 风险中心 | 准入 finding + 漂移 finding | 接受须原因与到期 |
| 策略闭环 | 现有 grant 状态机 + 读回 + 回滚 | 不另做企业 SoD / Break-glass |
| 运行时绑定 | 适配器安装状态 + 可选 OpenShell 目标 | 钩子掉了降到 L0，写在资产上 |
| 审计导出 | 只追加操作日志 + 回执链 `verify` | 可下载脱敏 JSON |

### 1.3 现场成功标准（可判定）

现场 10 分钟内，**只启动 `agentshield serve`**（可选已在跑的 Hermes / 已验明 OpenShell），能够：

1. 打开内嵌控制台，侧栏能走到「资产 / 权限 / 风险 / 签发 / 回执」，观感对齐企业壳（磨砂侧栏、PageHeader、表格密度），顶栏仍标明「本地模式 · 单用户」+ 平台档位。
2. 盘点页列出本机平台与 Skill；点进详情能看到 evidence 与声明工具。
3. 权限页能解释当前 subject 的五态；无 L3 时 effective 列为空或「未读回」，不得把 deployed grant 显示成 effective。
4. 红蓝对抗仍成立：toxic Skill → quarantine；官方风格 → 人批 grant → 越权工具 deny → `verify` 通过。
5. 不登录、不起 `:8600`、不连 PostgreSQL。

评委回家复现路径保持 `AGENTSHIELD.md` 三步；台账页是加分主界面，不是新的前置依赖。

### 1.4 明确不作为本计划成功标准

- 企业控制面 12 路由全部出现且后端为空壳。
- 多租户、OIDC、Edge 注册码、k8s 舰队盘点、变更中心、Break-glass。
- `support_matrix` 改为 `supported`（须新证据 + 重签，另案）。
- 合入 `main`、打 GitHub Release（除非另行明确要求）。

---

## 2. 现状基线（2026-09-05）

### 2.1 已经具备的能力

**发现（浅）**

- `internal/inventory`：只读扫描 Hermes / OpenClaw / CodeBuddy / Trae / Claude Code / Codex 的已知配置与 `SKILL.md` 目录，以及众所周知 MCP 客户端配置。
- 产出 `platform_config`、`skill_dir`、`hermes_profile`、`openclaw_agent`、`mcp_server` 候选，带 content hash、是否已准入；不启动 MCP、不读密钥正文。
- **P1 已补**：Hermes `profiles/*`、OpenClaw `agents.list`、`platform_toolset_modes` 键作为 tool 域 declared。
- **MCP 原生只读已补**：`mcp_server` 候选（env 只出键名、url 只留 `scheme://host`）。可选 `--connectors-dir` 仍可 **exec** `connectors/mcp`，禁止 import。

**管控（硬闭环，平台相关）**

- 准入：静态规则 + 决策表；toxic → `quarantine`（退出码 3）。
- 签发：人 `--approve-as` / 控制台点击；default-deny；`CompilePolicy` 与 Python `artifact_hash` 对等。
- 运行时：`POST /v1/decide` + 签名回执链；block 模式 API 不可达则拒绝。
- 适配器：Hermes 插件、OpenClaw `policy-exec`、CodeBuddy PreToolUse；Trae 仅审计。
- OpenShell：PATH / `SIQ_AS_OPENSHELL_ENV_SH` 发现 CLI；`status` 握手验明；禁止 `gateway start`。

**算法共用（不要再搬一遍 Python）**

- 威胁规则包与控制面逐字节一致；`internal/threat` 为 Go 移植（AST 四条仍缺，规格已记）。
- 合同：candidate / evidence / permission-fact / desired-policy / receipt。

**证据**

- Hermes Linux L0–L2：[`docs/evidence/agentshield/hermes-linux-2026-09-05/`](./evidence/agentshield/hermes-linux-2026-09-05/README.md)（隔离、附条件准入、人类批准、授后 `web_fetch` deny、`verify`）。
- OpenShell 接入 research-engine 隔离网关：[`docs/evidence/agentshield/openshell-siq-research-engine-2026-09-05/`](./evidence/agentshield/openshell-siq-research-engine-2026-09-05/README.md)（probe + 身份；矩阵仍不标 `supported`）。
- 矩阵：**没有任何一行 `supported`**。诚实口径不变。

### 2.2 缺口（相对企业台与相对已写规格）

| ID | 缺口 | 性质 |
| --- | --- | --- |
| G1 | 本地 UI 五页、无资产详情/五态权限/风险运营页 | 观感 + 叙事（参赛权重高） |
| G2 | inventory 未扫具名 Agent 实例 | **P1 已补** profiles / agents.list；MCP 配置只读已补。k8s/docker 仍默认不扫 |
| G3 | 无资产 confirm/dismiss | 企业有、本地无；规格未强制文件布局 |
| G4 | 权限事实散落在 grant/receipt/openshell，无聚合 API | 数据已有，缺对照面 |
| G5 | 五域编辑器只在企业详情页 | 本地签发偏 CLI |
| G6 | 无漂移 finding（读回 vs 已部署） | L3 已能读回，未产品化 |
| G7 | Skill 哈希变化 / 目录消失不自动 revoke；钩子丢失不降 L0 | 先前 P0 加固，与台账展示绑定 |
| G8 | `agentshield sync --control-api` | **已落地**（默认不跑；缺凭据跳过；失败不改本地决策） |
| G9 | Connector 子进程 | **已落地**为可选 `--connectors-dir` / `SIQ_AS_CONNECTORS_DIR` |

### 2.3 本机观察到的双入口（开发环境，非产品承诺）

- `127.0.0.1:47611`：`agentshield serve`（本地台）。
- `127.0.0.1:52741`：`apps/web` Vite（企业台 `/agents`）。
- `127.0.0.1:8600`：control-api uvicorn（企业 API）。

三者独立。W7 **不**把后两者变成评委前置。

---

## 3. 架构决策

落地前视为已拍板。若要推翻，先改本文再改规格再改代码。

| 编号 | 决策 | 理由 |
| --- | --- | --- |
| D1 | **作品主叙事仍是 AgentShield**。评委入口继续 `AGENTSHIELD.md`。 | 赛事是 Agent Skills，不是企业 SaaS 控制面赛道。 |
| D2 | **现场主界面是本地台账**，信息架构向企业 `/agents` 对齐，而不是维持「五页运维台」。 | 台账是参赛加分项；进程依赖不是。 |
| D3 | **本地是唯一决策事实源。** 禁止 `src/local` 调用 Control API `:8600`。 | 避免两套 allow/deny；评委复现零库。 |
| D4 | **企业控制面保持独立可运行。** `npm run build`、`AuthGate`、`:8600` 行为不变。 | 公司台账与 SIQ 平台接入仍走原产品；不毁 Phase 0–2。 |
| D5 | **能力用 Go 文件态重做，不嵌入 FastAPI/Postgres/OIDC。** | `apps/agentshield` 仅标准库；交叉编译不变量。 |
| D6 | **Connector 只可 `exec` 子进程，不可 import。** 无 `--connectors-dir` 时原生扫描仍可用。 | 规格 2026-09-04 修正；保持 stdlib。 |
| D7 | **grant 承担策略对象。** 不移植企业 SoD（提出者≠批准者）与 Break-glass。单用户控制台标明本地模式。 | 一人笔记本上做 SoD 是假治理。 |
| D8 | **`sync --control-api` 放在最后一期，默认关闭。** 上传失败不影响本地决策。 | 规格 §2.4；中心档案库，不是指挥棒。 |
| D9 | **不改 `hermes-agent`、`research-engine` 或其他兄弟仓。** OpenShell 用 `ENV_SH` 接入已有网关。 | 工作区边界。 |
| D10 | **两套 UI 继续双构建。** `VITE_APP=agentshield` → embed；默认构建 → 企业台。设计系统（`index.css`、PageHeader、SimpleTable、icons）共用。 | 规格 §3.10。 |

```
本机平台 / Skill /（可选）已验明 OpenShell
        │ 只读盘点 + 钩子
        ▼
agentshield（唯一裁决）
  inventory → assets → admit → grant → decide/receipt
  openshell 读回 ──► 仅此时 network 等可 effective
        │
        ▼
本地控制台 src/local（embed）
  总览 · 资产 · 权限 · 风险 · 签发 · 回执 · 绑定 · 设置

可选（非现场）：sync --control-api → 企业控制面（档案，不反向决策）
```

---

## 4. 能力映射（企业 → 本地）

| 企业功能 | 处置 | 本地落点 |
| --- | --- | --- |
| Layout / 字体 / 表格 / 详情密度 | **借 UI** | `src/local/Layout.tsx` 与企业壳对齐；导航按 §5 扩展 |
| `/agents` 列表 + 确认/驳回 | **借交互** | 资产列表；状态 `candidate \| needs_review \| confirmed \| dismissed` |
| `/agents/:id` 证据 + 五域编辑 | **借交互** | 资产详情；编辑写入 grant 草稿，批准后 deploy |
| `/permissions` 五态分色 | **借语义** | `GET /v1/permissions` 聚合，禁止把 inferred 画成 effective |
| 「同步 OpenShell」+ 漂移 Finding | **借语义** | 有 L3 才启用；不可达 fail-closed，不把「没查到」当「没漂移」 |
| `/findings` 风险接受 | **轻量借** | 文件态 findings；到期重开；无 Python worker |
| `/policies` `/changes` SoD | **不借状态机** | 签发页展示 grant 生命周期即可 |
| `/runtime-bindings` | **轻量借** | 适配器 + OpenShell 目标；吊销 = uninstall 或撤销 sandbox 绑定声明 |
| `/environments` 注册码 / 设备密钥 | **不借** | 设置页一行「本机 = 唯一环境」 |
| `/audit` Outbox Webhook | **借导出** | `audit.jsonl` + 回执 `verify`；无 Webhook |
| OIDC / 多租户 / LLM 分类器 | **不借** | — |
| 威胁静态检测 | **已有** | 补控制台展示，不重写分析器 |
| 11 Connector 舰队（docker/k8s） | **默认不做** | P2 可选 hermes/openclaw/directory/mcp 子进程 |

---

## 5. 本地信息架构（目标）

企业导航 10 项压缩为本地 8 项。顶栏徽章规则不变（规格 §3.10）。

| 路由 | 标题 | 数据 | 对应企业页 |
| --- | --- | --- | --- |
| `/overview` | 总览 | 档位、链头、资产/准入/deny 计数 | `/overview` |
| `/agents` | 智能体资产 | 盘点 + 资产状态；详情 `/agents/:id` | `/agents` |
| `/permissions` | 权限视图 | 五态聚合；可选 subject 过滤 | `/permissions` |
| `/findings` | 风险中心 | 准入 + 漂移；接受/到期 | `/findings` |
| `/grants` | 签发 | 现有 grant 审批/重叠 | `/policies` 的本地等价 |
| `/receipts` | 回执 | 现有链；deny 高亮；验签 | `/audit` 的运行时切片 |
| `/bindings` | 运行时绑定 | adapter status + OpenShell doctor 摘要 | `/runtime-bindings` |
| `/settings` | 设置 | enforcement_mode、actor、OpenShell ENV | `/settings` |

兼容：旧书签 `/inventory`、`/admissions` 重定向到 `/agents`（准入记录改到资产详情或签发旁路列表，避免丢数据）。

**禁止**：把上述路由接到 `AuthGate`；禁止 token 进 `localStorage` / 地址栏。

---

## 6. 数据与 API（回写规格后实现）

### 6.1 状态目录增量

现有布局见规格 §2.2。W7 新增（均 0600，只新建或追加）：

```
<state>/
  assets/<asset_id>.json           纳管投影（从 candidate 确认后产生）
  assets/<asset_id>.<seq>.json     状态变更不改写
  findings/<finding_id>.json
  audit.jsonl                      操作审计：admit/grant/revoke/adapter/dismiss
```

资产记录最小字段：`asset_id`、`source`（candidate_id / source_type / locator）、`framework`、`name`、`status`、`evidence_ids`、`admission_id?`、`grant_id?`、`dismiss_reason?`、`dismiss_until?`、`updated_at`、`signature`。

Finding 最小字段：`finding_id`、`rule_id`、`severity`、`status`（open / accepted / reopened）、`subject_ref`、`evidence_ids`、`source`（admission \| drift）、`accept_reason?`、`accept_until?`、`signature`。

### 6.2 HTTP 增量（均 bearer + loopback）

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/v1/assets` | 最新盘点与已确认资产的合并视图 |
| GET | `/v1/assets/{id}` | 详情：候选、证据、关联 admission/grant、档位 |
| POST | `/v1/assets/{id}/confirm` | 写入 confirmed；body `actor_id` |
| POST | `/v1/assets/{id}/dismiss` | body：`actor_id`、`reason`、`until`（必填） |
| GET | `/v1/permissions` | query：`subject_id`；返回 facts[]，每条含 state/domain/authority/revision/evidence_ids |
| POST | `/v1/grants/{id}/patch-desired` | 五域补丁；仅 `pending`/`rejected` 以外的草稿态；fs/process 写入则标 `static_domains_unavailable` |
| GET | `/v1/findings` | 列表 |
| POST | `/v1/findings/{id}/accept` | `actor_id` + `reason` + `until` |
| POST | `/v1/openshell/drift-check` | 读回 vs 已部署 grant；不一致写 finding；网关失败 5xx + 明确错误，不写「无漂移」 |
| GET | `/v1/audit` | 最近 N 条操作（无密钥、无参数原文） |

五态聚合规则（实现锁死）：

| state | 唯一合法来源 |
| --- | --- |
| declared | admission / Skill frontmatter / 读到的 toolset 声明 |
| inferred | grant 推导（如 process.forbid_privilege_escalation） |
| observed | receipt 决策结果 |
| effective | OpenShell（或其它执行后端）读回命中的 fact；fs/process 禁止 |
| unknown | 后端未报告该能力 |

### 6.3 盘点加深（对齐规格 §3.5）

原生扫描补齐，**不**把 k8s/docker 当默认：

1. Hermes：`profiles/*/` 各出一条 agent 候选；读取 `platform_toolset_modes` 作为 tool 域 declared（只读结构，不执行）。
2. OpenClaw：解析 `agents.list`（或等价键），密钥值不出结构体。
3. 周期：`serve` 已有约 5 分钟扫描未准入 Skill 的意图；W7 扩展为刷新资产投影，哈希变化触发 G7。
4. MCP：众所周知客户端 `mcp.json` 原生只读，产出 `mcp_server`；安全边界对齐 `connectors/mcp`，但不 import、不连接、不 exec command。

可选 `--connectors-dir`：对 `connectors/{hermes,openclaw,directory,mcp}` `exec` + NDJSON；超时 60s、输出上限 8MB、失败记 skipped，不阻断原生结果。

### 6.4 P0 加固（与台账同时设计）

| 事件 | 行为 |
| --- | --- |
| 已准入 Skill 的 content_hash 变化 | 新 admission `supersedes`；旧 grant → `revoked`（规格 §3.6 已有，核对是否落地） |
| Skill 目录消失 | 资产标 stale；已部署 grant revoke；UI 说明「发现记录还在，运行时不可达」 |
| 适配器/钩子从配置中消失 | 该平台档位降 L0；资产与顶栏同时显示「发现得到、当前无法阻断」 |
| 无 L3 且 grant 含出网 | 工具层仍拦 web_fetch 等；顶栏「仅工具层拦截」；权限页 effective 为空 |

无 L3 时收紧 exec：出网类 exec（curl/wget/nc）在 block 模式默认 deny，除非 grant 显式允许对应 host。此条回写 receipt 引擎规格后再改代码。

---

## 7. 分期

每期结束必须：`gofmt` / `go vet` / `go test ./...`、四目标交叉编译、`npm run build:local` 后 embed、相关 Go 合同样例仍能过 Python schema。改 `skills/agentshield` 则用 `AGENTSHIELD_RELEASE_SEED` 重签（seed 在 gitignore）。

### P0 — 台账壳与五态对照（优先，参赛观感）**已落地（2026-09-05）**

**目的**：不增加拦截力，让现场主界面像 `/agents`。

- 本地 Layout 导航改为 §5；企业组件密度对齐。
- `GET /v1/permissions` + `/permissions` 页。
- 盘点升级为 `/agents` 列表；`/agents/:id` 只读详情（证据、声明工具、准入 verdict、关联 grant）。
- 总览 KPI：平台档位、未准入 Skill 数、最近 deny 数。

**验收**：不起 `:8600`，打开 47611 能讲完「有哪些 Skill、权限哪几态、哪次调用被拒」。

### P1 — 发现对齐规格 + 资产生命周期 **已落地（2026-09-05）**

**目的**：真正补「发现智能体」，而不只是发现框架。

- inventory：profiles、agents.list、toolset 声明。
- assets 状态机 + confirm/dismiss API 与 UI。
- G7：哈希变化 / 目录消失 / 钩子丢失。

**验收**：本机 Hermes 多 profile 时列表多于 1 条平台行；驳回到期后自动回到候选（serve 周期或下次 inventory）。

### P2 — 管控对照：编辑、漂移、绑定 **已落地（2026-09-05）**

**目的**：权限从「能拦工具」变成「能编、能对照、能报漂移」。

- 详情五域编辑 → `patch-desired` → 人批 → deploy。
- 有 L3：`drift-check`；无 L3：按钮禁用并写原因。
- `/bindings`：adapter install/uninstall 与 OpenShell doctor 摘要。
- exec 出网收紧（规格回写后）。

**验收**：改网络 allow → 批准 → deploy；有网关则读回 revision 一致；人为改网关后 drift finding 出现。无网关演示不假装 effective。

### P3 — 风险、审计、可选同步 **已落地（2026-09-05）**

- `/findings` 全页；接受/到期重开。
- `audit.jsonl` + `GET /v1/export` / `agentshield export` 脱敏包。
- `agentshield sync --control-api`：Edge `POST /edge/v1/batches`；默认不跑；缺凭据退出 0；失败不改本地。
- 可选 `--connectors-dir`（失败记 skipped）。

**验收**：评委可从设置页或 CLI 导出脱敏 JSON。企业台若已登记本机公钥并签发 scan 任务，sync 可上传候选/证据；未登记则跳过，不挡比赛。

### P3+ — MCP 配置原生只读 **已落地（2026-09-05）**

- inventory 扫众所周知 MCP 客户端配置，产出 `source_type=mcp_server`。
- 不连接、不 exec command；env 只出键名；url 只留 `scheme://host`；符号链接与畸形 JSON 记 `skipped`，不让整个 `inventory.Run` 失败。

**验收**：fixture 含 token/userinfo 时整份 inventory JSON 不含密钥原文；`platforms` 含 `mcp`。

### 建议日历（相对提交窗口）

| 窗口 | 内容 |
| --- | --- |
| 现在 → 提交前 | **P0 必做**；P1 尽力；P2 有 L3 环境则做漂移，否则文档标明 |
| 提交后 → 决赛 | P2 收口、P3 导出、OpenClaw/CodeBuddy E2E 证据 **已归档（不改矩阵）** |

---

## 8. 测试与诚实披露

### 8.1 测试

- 五态聚合：同一 fixture 下 declared/inferred/observed/effective 不得串态；fs fact 调用 `MarkEffective` 必须失败。
- dismiss 缺 reason/until → 4xx。
- drift-check：假 CLI 返回与 grant 不一致 → finding；CLI 失败 → 错误，finding 计数不增加「已同步无漂移」。
- 钩子配置去掉 agentshield 标记后，status 档位为 L0。
- UI 构建：`npm run build`（企业）与 `npm run build:local` 均成功，互不覆盖错误入口。

### 8.2 演示脚本（W6 增量）

在 `AGENTSHIELD.md` 增加「台账演示」一节，放在三步对抗**之后**：打开控制台 → 资产 → 权限五态 → 回执 deny。注明不需要登录。

### 8.3 对外口径

- 发现范围：**本机**平台、profile/agent 列表、Skill 目录、MCP 客户端配置；不是公司舰队。
- 管控范围：已装适配器的平台之工具层；L3 仅已验明 OpenShell 的网络段读回。
- Trae：发现得到，不能阻断。
- 企业控制面：完整产品仍在，现场评委不必启动。

---

## 9. 风险与依赖

| 风险 | 缓解 |
| --- | --- |
| P0 过大导致三步对抗回归 | P0 以聚合与展示为主，不改 decide 热路径；E2E `server_test.go` 必须保持绿 |
| 本地页长得像企业台，评委去找登录 | 顶栏「本地模式 · 单用户」不可移除 |
| 把 deployed 说成已在沙箱生效 | UI 与 API 分层着色；无 revision 不渲染 effective |
| 改 Skill 包忘重签 | 发布清单测试；CI 或本地 `manifest-verify` |
| OpenShell 连到 OpenClaw 端口 | 维持 identity fail-closed；不猜端口 |
| 规格与本文双源 | 每期开工前把 §6 回写 spec；本文标注「已回写 / 未回写」 |

---

## 10. 文档回写清单

每期代码前更新规格，避免「计划是事实源、规格是事实源」双头。

| 规格章节 | 回写内容 |
| --- | --- |
| §2.2 状态布局 | assets / findings / audit |
| §2.4 | 保持「可选、非现场」；注明台账 UI 是现场主界面，sync 仍非现场 |
| §3.5 | 实现清单与「已完成 / 未完成」；去掉「inventory 完成」中与 profiles 不符的表述 |
| §3.8.1 HTTP | §6.2 新端点 |
| §3.10 UI | §5 路由；`/inventory` 重定向 |
| §9 里程碑 | 增加 W7，状态按 P0–P3 勾选 |
| `AGENTSHIELD.md` | 台账演示节；仍声明企业 API 评委不必跑 |
| `apps/agentshield/AGENTS.md` | 新包职责行（assets/findings 若拆包） |

企业 README 增加一句：本地门禁台账是 AgentShield embed UI；本 README 描述的控制面仍用于多环境/多租户部署。

---

## 11. 工作约定（沿用，不新开例外）

- 实现语言：`apps/agentshield` 仅 Go 标准库。
- 提交格式：`<scope>: <主题>`（如 `agentshield:` / `web:` / `contracts:`）。
- 用户未要求时不 commit、不合 `main`、不打 Release。
- token、signing seed 不进 git、截图、聊天、localStorage。
- 回复与提交说明用简体中文。

---

## 12. 未决项（不阻塞 P0）

1. `/admissions` 独立页是否保留为「准入流水」二级入口（建议 P0 做重定向，P1 在资产详情内嵌列表）。
2. 资产 ID 稳定性：`skill:hermes:name@hash12` 在改名后是否迁移（建议 locator + hash 为主键，name 可变）。
3. 本机是否默认扫描 Claude Code / Codex 仅作 L0 展示（inventory 已能探测配置；适配器未做则只发现不管控）。
4. OpenClaw / CodeBuddy linux E2E 证据已归档（隔离 HOME；不改矩阵）。剩余：GitHub Release、是否把矩阵行改成 `supported`（须重签）。

---

## 13. 立即执行顺序

1. 评审本文。异议只改决策表 §3，不直接改代码。
2. 回写规格 §2.2 / §3.8.1 / §3.10 中 **P0 所需** 段落。
3. 实施 P0（权限聚合 API + `/agents` 只读详情 + 导航对齐）。
4. P0 验收通过后再开 P1。

当前建议：**先做 P0。** 它把已有发现/管控能力变成评委能看懂的台账，且不绑定 `:8600`。
