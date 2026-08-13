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

## 安全不变量（任何改动不得破坏）

1. tenant_id 只从验证身份派生；对象级端点先定位（404）后权限（403）；
2. Secret 明文不落库、不进日志/审计/outbox（只存哈希或引用）；
3. 审计与状态变化同事务；高风险写操作审计缺失即失败关闭；
4. Edge 凭据只存哈希，吊销即时生效（每次请求在线校验）；
5. 模型输出不能直接创建 effective 权限或通过审批；
6. 每批 evidence 必须被本批 candidate 引用；
7. 生产模式（非 SIQ_AS_DEV）禁止 SQLite、自动建表、X-Dev-* 身份头。

## 开发约定

- Python ≥3.12：`uv sync --dev`、`uv run ruff check app`、`uv run pytest`；迁移必须 Alembic 且可在干净库回放；
- Go ≥1.22：标准库优先；Connector 只经 `edge/agent/protocol` 共享包引用合同类型；
- Web：`npm ci && npm run build`；token 永不落 localStorage；
- 提交：`<scope>: <简洁主题>` 格式（如 `contracts:`、`control-api:`、`edge:`、`web:`、`docs:`）；安全修复必须带负向测试证明旧行为被拒绝；
- 推送注意：本机环境变量 `GITHUB_TOKEN` 已失效，gh/git 推送用 `env -u GITHUB_TOKEN gh/git ...` 走 keyring 凭据。

## 测试要求（按变更类型）

| 变更 | 最低验证 |
| --- | --- |
| 合同 Schema | JSON Schema 示例校验 + 实现方字段同步 + 兼容测试 |
| Control API 路由/模型 | 单测 + 租户隔离负向 + 迁移回放 |
| 安全相关 | 正负向 + 审计/outbox 断言 |
| Connector | 负向语料（恶意配置/符号链接逃逸/超大文件/.env 拒绝） |
| Web | `npm run build` + 类型检查 |
