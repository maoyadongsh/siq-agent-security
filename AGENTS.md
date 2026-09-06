# siq-agent-security 仓库指南

本仓库是 SIQ Agent Security 产品的独立代码仓（受 `/home/maoyd/siq/AGENTS.md` 工作区指南约束，本文件在其之上细化）。

## 边界

- 不 import 兄弟仓库内部代码、不查询兄弟仓库数据库；
- SIQ 专属能力只在 `connectors/siq`（当前未实现），经版本化 API/事件接入；
- 合同变更先改 `packages/contracts/`（升版本），再同步实现方与测试。

## 事实源顺序

1. `packages/contracts/*.schema.json` + `connector-protocol.v1.md`（合同事实源）；
2. 设计文档 v0.2 与 ADR（`docs/adr/`）；
3. 实现与测试。

siq-agent-security（本地 Agent 形态，ADR-011）在此之上再加一层：ADR-011 → `docs/agentshield-design-v1.md`（方案）→ `docs/agentshield-dev-spec-v1.md`（规格，实现以此为准）→ 合同。W7 本地台账增量见 `docs/agentshield-local-ledger-dev-plan-v1.md`（先回写规格再实现）。规格与实现不一致时先改规格再改代码；就近约定见 `apps/agentshield/AGENTS.md`。

## 安全不变量（任何改动不得破坏）

1. tenant_id 只从验证身份派生；对象级端点先定位（404）后权限（403）；
2. Secret 明文不落库、不进日志/审计/outbox（只存哈希或引用）；
3. 审计与状态变化同事务；高风险写操作审计缺失即失败关闭；
4. Edge 凭据只存哈希，吊销即时生效（每次请求在线校验）；
5. 模型输出不能直接创建 effective 权限或通过审批；
6. 每批 evidence 必须被本批 candidate 引用；
7. 生产模式（非 SIQ_AS_DEV）禁止 SQLite、自动建表、X-Dev-* 身份头。

siq-agent-security 本地模式（`apps/agentshield/`）额外遵守：

8. `effective` 只能来自后端读回；admission 只产 `declared`，grant 只产 `declared`/`inferred`，receipt 只产 `observed`；
9. 签名私钥只存状态目录，适配器、UI、SKILL.md 脚本永不持有；准入/签发/回执文件只追加或新建，不改写；
10. 被扫描的 Skill 内容与钩子参数永不执行、导入或 `eval`；持久化只存 sha256 与脱敏、限长的 excerpt；
11. `enforcement_mode=block` 下决策服务不可达即拒绝（fail-closed）；`audit_only`/`warn` 只能 allow 并记 `advisory_action`；
12. 「有威胁模式」≠「隔离」：能力需求（sudo、出网、写路径、`allowed-tools`）升级为 declared 事实交 grant；只有欺骗用户、隐藏指令、提示注入、凭据外传、完整性失败才 quarantine。

## 开发约定

- Python ≥3.12：`uv sync --dev`、`uv run ruff check app`、`uv run pytest`；迁移必须 Alembic 且可在干净库回放；
- Go ≥1.22：标准库优先；Connector 只经 `edge/agent/protocol` 共享包引用合同类型；`apps/agentshield` 仅 stdlib，第三方依赖需 ADR；
- 规则包 `threat_rules.v1.json` 是 Python/Go **共享文件**（`apps/control-api/app/data/` 与 `apps/agentshield/internal/rulepack/data/` 两份由测试锁定一致）：模式必须 RE2 兼容且 CPython 语义等价，改动两侧测试都要跑；
- 平台适配器（`adapters/runtime/*-agentshield/`）只做钩子 ↔ HTTP 映射，不含规则、判定或密钥；改写用户配置（如 CodeBuddy `settings.json`）必须先备份、可卸载；
- Skill（`skills/siq-agent-security/`）遵守 agentskills.io 规范：`description` ≤60 字符一句话句号结尾；正文明确「裁决由二进制产出，模型不判断安全性」；
- Web：`npm ci && npm run build`；token 永不落 localStorage；
- 提交：`<scope>: <简洁主题>` 格式（如 `contracts:`、`control-api:`、`edge:`、`web:`、`agentshield:`、`adapters:`、`skills:`、`rulepack:`、`docs:`）；安全修复必须带负向测试证明旧行为被拒绝；
- 推送注意：本机环境变量 `GITHUB_TOKEN` 已失效，gh/git 推送用 `env -u GITHUB_TOKEN gh/git ...` 走 keyring 凭据。

## 测试要求（按变更类型）

| 变更 | 最低验证 |
| --- | --- |
| 合同 Schema | JSON Schema 示例校验 + 实现方字段同步 + 兼容测试 |
| Control API 路由/模型 | 单测 + 租户隔离负向 + 迁移回放 |
| 安全相关 | 正负向 + 审计/outbox 断言 |
| Connector | 负向语料（恶意配置/符号链接逃逸/超大文件/.env 拒绝） |
| Web | `npm run build` + 类型检查 |
| 规则包 | Python 三组测试（analysis/rulepack/baseline）+ Go `internal/rulepack` `internal/threat` 对等测试 + `detection-baseline.md` 数字同步 |
| 本机门禁 Go 模块（`apps/agentshield`） | `gofmt -l . && go vet ./... && go test ./...` + 三 OS 交叉编译；输出样例回灌 Python schema 校验 |
| 适配器 | 每平台一条「装 → 扫 → 授 → 越权被拒」E2E + fail-closed 负向（服务不可达时 block 模式必须拒绝） |
| Skill 包 | 用自建二进制 `admit` 自扫描不得 quarantine；四平台安装验证 |
