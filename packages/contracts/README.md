# 合同包（packages/contracts）

本目录是产品对外与对内合同的**事实源**：跨组件共享的 JSON Schema 与子进程协议规范。任何破坏性变更必须先升 schema 版本，再同步所有实现方与测试，杜绝"实现漂移即合同"。

领域信封 `event-envelope.schema.json` 与 Document Engine 的同名文件**不是**同一 schema（一边 integer `schema_version`，一边 document 专用 enum）。共享字段以 `event-envelope-core.schema.json` 为权威，同步命令见 Document Engine `packages/contracts/json-schema/events/README.md`。

## 合同文件清单（10 份）

| 文件 | 内容 | 关键字段/约定 | 对应设计文档 |
| --- | --- | --- | --- |
| `admission.schema.json` | Skill 安装前准入结论（AgentShield） | 三值 `verdict`；`findings.disposition`（quarantine / declare / info）与 verdict 用 `if/then` 锁定自洽；`declared_facts` 只能 `state=declared`、`effect=allow`；`over_limit` / `symlink_escape` 强制 quarantine；`content_hash` 用于 tool pinning | ADR-011、设计方案 v1 §4.1 |
| `grant.schema.json` | 最小权限签发 | `default_effect` 恒为 `deny`；`approved_by.actor_type` 只允许 `human`；approved 及之后禁止 `unresolved` 重叠；`effective` 必须带 `effective_readback` 与逐条 `authority_revision`/`readback_evidence_id`；按 `platform` 强制输出 `hermes_toolset_allowlist` / `openclaw_tool_policy`；`static_domains_unavailable` 显式承认 fs/process 不可热下发 | ADR-011、ADR-003/004、§12.4 |
| `receipt.schema.json` | 每次工具调用的签名回执 | 哈希链（`seq`/`prev_hash`/`hash`/`sig`，创世 prev 全 0）；四种处置 allow/deny/hold/redact；deny/hold/redact 必须有 `reason`；`audit_only` 只能 allow 并以 `advisory_action` 记录；只存 `params_digest` 与脱敏 `params_excerpt`，禁止参数原文；`taint_labels` + `trifecta` | 设计方案 v1 §4.2 |
| `skill-manifest.schema.json` | AgentShield Skill 发布清单 | 二进制按 OS × arch 钉 `sha256`；规则包版本 + 公钥；`support_matrix` 按平台 × OS 标 L0–L3，`audit_only` 不得宣称 L2，macOS/Windows 的 L3 必须写 `requires`；`description` ≤60 字符句号结尾；清单本身签名 | ADR-011 D1/D5 |
| `candidate.schema.json` | 发现阶段的智能体候选 | `evidence_ids` 必填（minItems 1）、确认/驳回生命周期 | §10.2 / §10.5 |
| `evidence.schema.json` | 可验证证据 | `collected_at`、`expires_at`（新鲜度窗口）、`signature`（Edge 签名） | §10.5 |
| `permission-fact.schema.json` | 权限事实 | 五态 `state`（declared/inferred/observed/effective/unknown）、`delegated_user` 委托维度、authority/revision 溯源 | §12.3 |
| `desired-policy.schema.json` | 后端无关的期望策略 | `enforcement_mode` 渐进档位（audit_only/warn/block）、selector、版本与状态 | §14.1 |
| `event-envelope.schema.json` | 领域事件信封 | event_id/type/occurred_at/tenant/environment/actor/payload + integer schema_version | §18.3 |
| `event-envelope-core.schema.json` | 跨域共享身份字段（ENG-03 权威副本） | event_id/type/occurred_at/tenant_id/request_id/payload；与 Document Engine 字节一致 | SIQ_CROSS_REPO_DEVPLAN ENG-03 |
| `connector-protocol.v1.md` | Edge ↔ Connector 受限子进程协议 | NDJSON、op 清单、错误码、负向语料、签名与新鲜度约定 | §26.1 |

控制面以 `apps/control-api/app/tests/test_schema_contracts.py` 守护示例与实现方字段同步：schema 示例校验 + 实现方字段一致性，任何一侧漂移即测试失败。ADR-011 四份合同的每条 `if/then` 不变量在该文件各有一条负向测试。

### AgentShield 四合同的数据流

```
SKILL.md → skill-manifest（校验二进制哈希）→ agentshield 二进制
  inventory ──► candidate + evidence（既有合同）
  admit     ──► admission（declared_facts ⊂ permission-fact 语义，state 恒为 declared）
  grant     ──► grant（facts 五态；effective 只能来自后端读回）+ desired-policy 引用
  serve     ──► receipt（哈希链 + Ed25519；平台适配器与模型无签名密钥）
```

Go 实现（`apps/agentshield/`，规划中）与 Python 实现（control-api）共用本目录 schema 与同一套语料；`engine.name` 字段区分双实现，一致性测试以此比对。

## 变更规则

1. **先改合同，后改实现**：Schema 或协议变更先在本目录升版本（文件内 `version`/文件名版本），同步更新所有消费方（control-api、edge/agent、connectors）；
2. **示例与实现必须同步**：schema 内 `examples` 同时是测试夹具来源，新增必填字段必须补示例；
3. **破坏性变更显式标注**：`connector-protocol.v1.md` 协议字段的增删改同样适用，Edge 与 Connector 两端同版升级。

## Connector 子进程协议 v1

Connector 是运行在 Edge Agent 侧的多语言插件（设计文档 §26.1：版本化 gRPC 或受限子进程协议）。首版采用**受限子进程协议**：Edge 以子进程方式调用 Connector，stdin/stdout 交换 NDJSON，每行一条消息。详细规范见 [`connector-protocol.v1.md`](connector-protocol.v1.md)（进程约定、错误码、负向语料、签名与新鲜度）。

### 消息格式

```text
请求：{"id":"<request_id>","op":"<op>","params":{...}}
响应：{"id":"<request_id>","ok":true,"result":{...}}
错误：{"id":"<request_id>","ok":false,"error":{"code":"...","message":"..."}}
```

### 操作（对齐设计文档 §10.2 合同）

| op | 参数 | 结果 | 约束 |
| --- | --- | --- | --- |
| `describe` | — | `ConnectorCapabilities`：version、支持对象、所需权限、可能读取的数据类别、最大输出字节数 | 每次调用不得超过 64KB |
| `validate_scope` | `scope` | `ValidationResult`：`valid`、`errors[]` | 必须拒绝空范围、根路径、模糊通配符、越权 Namespace |
| `plan_scan` | `scope`、`cursor`(可选) | `ScanPlan`：步骤清单、预估输出上限、增量依据 | 增量使用稳定 Cursor，不以客户端时间为唯一依据 |
| `collect` | `plan` | `EvidenceBatch`：`candidates[]`（candidate.schema.json）、`evidence[]`（evidence.schema.json）、`cursor` | 默认只读、可取消、可超时、限制文件数与字节数 |
| `checkpoint` | — | `Cursor` | 用于增量扫描 |
| `health` | — | `HealthReport`：版本、依赖可用性 | 10s 超时 |

### 硬性要求

1. Connector **不直接创建纳管资产**，只产生候选与证据；
2. 输出必须已脱敏：禁止 token、secret、`.env` 正文、私钥进入任何字段（`redaction_profile: "siq.redaction.v1"`）；
3. `evidence.signature` 由 Edge 在收包后统一签名，Connector 不负责签名；
4. 每批次 `evidence` 必须被本批次至少一个 `candidate.evidence_ids` 引用（孤儿证据控制面拒绝）；
5. Connector 版本升级必须通过兼容与安全测试（负向：恶意配置/超大文件/符号链接逃逸）。

### 已实现的 Connector

| Connector | 语言 | 状态 | 负向测试 |
| --- | --- | --- | --- |
| hermes | Go | 已实现（build/vet/test 全绿） | scope 校验/符号链接逃逸/.env 拒绝/截断；toolsets → declared 工具权限事实 |
| directory | Go | 已实现（build/vet/test 全绿） | 空范围拒绝（无默认范围）/符号链接逃逸/.env 永不读取/限额截断 |
| openclaw | Go | 已实现（L1/L2 只读，build/vet/test 全绿） | 发现 agents.list + declared model/workspace 权限事实；auth-profiles 永不读（只记大小）；不写 OpenClaw 配置 |
| docker | Go | 已实现（build/vet 通过） | 环境变量值不出机（结构体无 Env 字段）；**负向测试待补** |

## Enforcement Adapter 合同

合同定义见设计文档 §15.3（OpenShell Adapter）与 §16.2（Runtime Adapter）。首版实现位于 `apps/control-api/app/adapters/openshell/`（contracts / base / policy_compiler / fake_backend / client / cli_backend）：

- **FakeBackend 契约测试**覆盖：能力探测、revision 冲突、静态 generation、正负验证、回滚、unsupported 显式标记；
- **`openshell-cli` 后端**：已在 OpenShell v0.0.104 真实网关实测"审批 → `policy set` → 读回验证 → effective"闭环（含网络策略热更新，见根 README 与 `docs/compatibility.md`）；SIQ 侧正式迁移（v0.0.83 → v0.0.104）处于 canary 窗口期，runbook 见 `docs/openshell-v083-to-v0104-migration.md`；
- `adapters/enforcement/` 预留给未来的独立进程形态，当前为空（规划中）。

## 与实现的对应关系（如实核对）

- `desired-policy.enforcement_mode`：实现已落地——只允许升级（audit_only → warn → block），降级必须走 high_risk 变更单并审批（`apps/control-api/app/routers/policies.py`）；**已知限制**：openshell-cli 执行后端当前仅支持 `block` 档，`audit_only`/`warn` 策略在部署时返回 422（`openshell_cli_mode_unsupported`），待后端支持后方可实际部署；
- `permission-fact.delegated_user` 与五态 `state`：Edge 上传的 `permission_facts`（`EdgePermissionFactIn`）与 schema 字段一一对应；`effective` 状态仍只允许控制面派生（模型/Edge 上传不得声明 effective）；
- **重叠冲突语义（overlap）**：定义于设计文档 §12.4（deny-overrides 组合、selector 冲突编译期报错）；实现以编译期静态校验起步，显式冲突输出待补，本目录暂不提供对应 schema 字段——变更前先立项升版。
