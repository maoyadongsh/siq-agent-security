# ADR-011：AgentShield 可移植 Skill 形态（Skill + 本地二进制 + 平台适配器）

- 状态：**已采纳（暂行）**
- 日期：2026-09-04
- 依据：`docs/research/agentshield-market-survey-2026-09.md`；ADR-001 / 003 / 004 / 005；第三届 DGX Spark 黑客松「Agent Skills 开发挑战赛」赛制

## 背景

目标是让用户在任意支持 Agent Skills 规范的平台（OpenClaw、Hermes、WorkBuddy/CodeBuddy、Trae/TraeWork 等）安装一个 Skill，即获得本产品的智能体安全管控能力，并覆盖 Linux / macOS / Windows。

三个事实约束了形态：

1. **Skill 没有执行权。** 所有平台上 Skill 都只是 `SKILL.md` + 脚本 + 资源，由模型决定加载、由模型调用工具运行脚本。拦截工具调用、锁文件系统、拦出网只能由平台钩子/插件和 OS 沙箱完成。
2. **钩子能力因平台而异。** OpenClaw 有 `before_tool_call`（可 block / 改参 / requireApproval，超时 fail-closed）与 `security.installPolicy`（装前 allow/warn/block）；Hermes 有插件 `pre_tool_call`；CodeBuddy/WorkBuddy 有全局 `PreToolUse`，Skill 自带 hooks 仅限 `context: fork` 且默认关闭；Trae/TraeWork 无工具钩子。
3. **OpenShell 只在 Linux 原生强制。** macOS 经 Docker Desktop VM，Windows 经 WSL2 且官方标 Experimental。

现有产品是「Edge Agent + Connector（Go）→ Control API（FastAPI + PostgreSQL）→ Web 控制台」的企业控制面形态，不能直接装进个人桌面。

## 决策

### D1 形态：三件套，Skill 是入口不是执行体

| 件 | 职责 | 位置 |
| --- | --- | --- |
| `SKILL.md`（一份，按 agentskills.io 规范） | 引导模型：校验并启动本地二进制、注册当前平台适配器、把裁决结果呈现给用户 | `skills/agentshield/` |
| `agentshield` 本地二进制（Go，单文件，内嵌 Web 控制台） | 盘点、准入、签发最小权限、写签名回执、localhost 决策 API | `apps/agentshield/` |
| 平台适配器（薄） | 把平台钩子接到二进制的决策 API；无钩子平台注册为审计模式 | `adapters/runtime/<platform>-agentshield/` |

SKILL.md 正文只允许「运行脚本并呈现结果」，**裁决由二进制产出**，模型不做安全判断（ADR-003）。SKILL.md 第一步必须校验二进制哈希/签名——安全 Skill 本身也是供应链项。

### D2 检测核心用 Go 重写，不拉起 Python

- 规则包 `threat_rules.v1.json` 的 43 条正则中 42 条可直接在 Go RE2 运行（`(?i)` 受支持）；`threat-persist-crontab` 含负向前瞻 `(?![el]\b)`，需改写为等价的显式分支并补正负语料。
- 4 条 Python AST 规则（`threat-py-*`）在 Go v1 **不实现**；其对应的 3 条正则文本规则仍生效（`docs/detection-baseline.md` 已记录双层重叠）。`threat-py-dangerous-import` 无正则等价，v1 以正则补一条。AST 层列入路线图（tree-sitter 或纯 Go 词法），基线文档同步标注。
- 规则包签名验证、脱敏、`policy_compiler`、`permission-fact` 五态、Ed25519 签名全部移植为 Go 包；Python 侧保留为 control-api 实现，两边共用同一份 JSON 规则包与 `packages/contracts/` schema，以**同一套语料**做双实现一致性测试。
- 不引入 `fcntl` 一类 POSIX-only 依赖；文件锁用跨平台实现。

### D3 接受「本地单用户模式」，文件态只追加回执替代 PostgreSQL

本地模式定义：

- 单机、单用户、非多租户；`tenant_id` 固定为 `local`，不接受任何客户端自报身份。
- 状态目录：Linux `$XDG_STATE_HOME/agentshield`、macOS `~/Library/Application Support/agentshield`、Windows `%LOCALAPPDATA%\agentshield`。
- 回执 `receipts/YYYY-MM-DD.jsonl` **只追加、哈希链接**（每条含前条哈希），Ed25519 签名，密钥在状态目录内生成并只读。
- 权限事实、策略、准入结论以 JSON 文件存放，schema 与 `packages/contracts/` 一致。
- 可选：以现有 Edge 协议把候选/证据/回执同步到 Control API；同步是**追加上传**，本地不因失联而失效。

与仓库不变量的关系：生产禁止 SQLite/自动建表的规则**不变**；本地模式不使用任何关系库，也不声称是多租户生产部署。控制台在本地模式显式标注「本地模式 · 单用户」。

### D4 平台优先级：OpenClaw 与 Hermes 并列第一

| 优先级 | 平台 | 目标档位 | 理由 |
| --- | --- | --- | --- |
| P0 | OpenClaw | L0–L3 | 钩子最完整（装前 + 运行时 + requireApproval），官方已退役内置扫描器并把决策交给外部策略；NemoClaw 底座，与 NVIDIA 关联强 |
| P0 | Hermes | L0–L3 | 仓内已有 connector 与 patch 治理；`pre_tool_call` 可 block；黑客松原生运行面 |
| P1 | WorkBuddy / CodeBuddy | L0–L2 | 需写全局 `settings.json` `PreToolUse`，须用户确认且可卸载 |
| P2 | Trae / TraeWork | L0 | 无工具钩子，控制台必须标「审计模式，无法阻断」 |
| P2 | Claude Code / Codex | L0–L2 | 有 hooks，非本轮目标 |

档位定义：L0 审计（盘点 + 准入 + Skill Card + 控制台）；L1 安装门禁；L2 运行时回执与阻断；L3 OpenShell 策略下发。**Linux 全档；macOS/Windows 交付 L0–L2，L3 依赖 Docker/WSL2 并如实标注。**

### D5 仓库归属：不新开仓库

AgentShield 是 `siq-agent-security` 的本地 Agent 形态，代码、合同、Connector、规则包、检测基线都在本仓，另开仓库只会复制合同并制造漂移。因此：

- `skills/`、`apps/agentshield/`、`adapters/runtime/` 直接落在本仓根目录；
- 平台市场（ClawHub、TraeWork 上传、`hermes skills install`）需要「根目录即 Skill」或 zip 时，由 CI 从 `skills/agentshield/` 打 release zip 并附二进制哈希；
- 只有当市场分发**强制要求独立 git 仓**时，才新建一个仅含 `SKILL.md` + 安装脚本、由 CI 自动镜像的分发仓，源码不迁出。

## 后果

- 正：一份 Skill 跨平台投递；拦截能力按平台真实钩子诚实分档；本地形态与企业控制面共享同一合同与规则包；Go 单文件消除 Python/uv 分发与 Windows `fcntl` 问题。
- 负：Go/Python 双实现需要一致性测试维护；AST 层在 Go v1 缺席；无钩子平台只能审计，用户可能高估保护；WorkBuddy 需改用户全局配置。
- 需同步更新：`docs/detection-baseline.md`（Go 实现覆盖与差异）、`docs/compatibility.md`（新增平台 × OS × 档位矩阵）、`packages/contracts/`（admission / grant / receipt / manifest schema）。
