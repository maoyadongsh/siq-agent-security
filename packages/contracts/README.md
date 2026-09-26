# 合同包（packages/contracts）

本目录是产品对外与对内合同的**事实源**：跨组件共享的 JSON Schema 与子进程协议规范。任何破坏性变更必须先升 schema 版本，再同步所有实现方与测试，杜绝"实现漂移即合同"。

领域信封 `event-envelope.schema.json` 与 Document Engine 的同名文件**不是**同一 schema（一边 integer `schema_version`，一边 document 专用 enum）。共享字段以 `event-envelope-core.schema.json` 为权威，同步命令见 Document Engine `packages/contracts/json-schema/events/README.md`。

## 合同文件清单

下表列出关键合同与不变量，并非全目录清单。新增版本以实际 schema、固定向量和消费方测试为准；旧版文件保留不表示新请求仍可使用。

| 文件 | 内容 | 关键字段/约定 | 对应设计文档 |
| --- | --- | --- | --- |
| `change-execution.v1.schema.json` | 单份变更的部署与精确审计关联 | policy:read 基础读取、audit:read 独立门禁；有界历史/截断声明、验证枚举、不返回原始回执或异常 | [E147 规格](../../docs/development/enterprise-change-execution-e147-spec.md) |
| `change-review.v1.schema.json` / `change-review-decision.v1.schema.json` | 企业变更审查及快照约束决策 | 完整有界权限域、身份绑定摘要、旧内容拒绝、内容不完整禁止批准；旧审批接口保持兼容、不自动获得快照门禁 | [E146 规格](../../docs/development/enterprise-change-review-e146-spec.md) |
| `enterprise-ocsf-export.v1.md` | OCSF 事件导出与截断事实声明 | `audit:read`；租户与 `since` 过滤后按 `limit+1` 探测，正文不超过 `limit` 行；`X-SIQ-Export-Truncated: 0\|1`、no-store、NDJSON、时间升序再按 ID 稳定排序；审计 `count` 只计实际返回条数；探测行不入正文/日志/审计，不是完整归档，不引入 published/verified | 本仓合同 |
| `enterprise-discovery-schedule.v1.md` / `enterprise-discovery-schedule-pending-list.v1.md` | 企业周期发现计划及设备待确认列表 | 组织创建有界计划；设备列表只读分页，显式确认后才能 tick；发现不自动选择、不授权；active 不证明在线、采集成功或防护生效 | 企业自动接入收口 |
| `enterprise-framework-role-inventory.v2.md` | 环境/设备下的框架实例与角色来源投影 | 按页核验 v1/v2；OpenClaw/Hermes 来源严格配对；来源不可核对时为 null，不造 Skill 或运行加载事实 | 企业资产发现收口 |
| `enterprise-runtime-binding-identity.v1.md` / `enterprise-deployment-impact.v1.md` | 运行时绑定身份与部署影响只读投影 | 执行/预览/影响生成前重读身份；未知共享占用、Skill 隔离或执行确认能力不得提升为已核验 | 企业运行时绑定收口 |
| `local-task-activity-query.v1.schema.json` | 运行列表的时间、裁决筛选与摘要 | 完整验签后筛选再分页；最后回执序号倒序；时间范围左闭右开；观察回执不重复计为调用；不推断业务状态 | 本机规格 §3.10.1 |
| `local-runtime-check-activity.v1.schema.json` | 自检到可信运行记录的精确引用 | 仅管理会话 GET；全部自检回执唯一且同一完整绑定，完整快照验签；不猜任务 ID、不受首 500 条限制；响应不授予权限 | 本机规格 §3.10.1 |
| `admission.schema.json` | Skill 安装前准入结论（本机门禁） | 三值 `verdict`；`findings.disposition`（quarantine / declare / info）与 verdict 用 `if/then` 锁定自洽；`declared_facts` 只能 `state=declared`、`effect=allow`；`over_limit` / `symlink_escape` 强制 quarantine；`content_hash` 用于 tool pinning | ADR-011、设计方案 v1 §4.1 |
| `grant.schema.json` | 最小权限签发 | `default_effect` 恒为 `deny`；`approved_by.actor_type` 只允许 `human`；approved 及之后禁止 `unresolved` 重叠；`effective` 必须带 `effective_readback` 与逐条 `authority_revision`/`readback_evidence_id`；按 `platform` 强制输出 `hermes_toolset_allowlist` / `openclaw_tool_policy`；`static_domains_unavailable` 显式承认 fs/process 不可热下发 | ADR-011、ADR-003/004、§12.4 |
| `receipt.schema.json` | 每次工具调用的签名回执 | 哈希链（`seq`/`prev_hash`/`hash`/`sig`，创世 prev 全 0）；四种处置 allow/deny/hold/redact；deny/hold/redact 必须有 `reason`；`audit_only` 只能 allow 并以 `advisory_action` 记录；只存 `params_digest` 与脱敏 `params_excerpt`，禁止参数原文；`taint_labels` + `trifecta`；可选 intent/task/digest/authority_revision/bound 状态、reason_code、action_id、record_type、decision_receipt_id、task_seq/parent_action_id 均进入签名 | 设计方案 v1 §4.2 |
| `hold-status-request.v1.schema.json` / `hold-status.v1.schema.json` | 执行前只读本地审批查询 | capDecision 请求完整动作/前置回执身份及原参数；响应 pending/approved/denied/expired/consumed；不能批准、续期或生成新授权，状态来自签名回执恢复 | 开发规格 §10.2 |
| `hold-execution-reserve.v1.schema.json` / `hold-execution-status-request.v1.schema.json` / `hold-execution-status.v1.schema.json` | 审批后的可信单次重试 | capDecision 重呈原 hold 全部身份并绑定新的宿主调用 ID；先签名持久化 reservation 再允许执行；重启后无 observation 的 reservation 为 uncertain，禁止盲目再执行 | N06 可信重试规格 |
| `local-confirmations.v2.schema.json` | 个人确认窗口投影 | 在 v1 摘要绑定上增加 task、规范动作/效果、资源指纹、仅一次范围、平台恢复模式与 reserved/completed/uncertain 状态；不返回原始参数 | N06 可信重试规格 |
| `local-skill-update-source-save.v1.schema.json` / `local-skill-update-source-disable.v1.schema.json` / `local-skill-update-schedule-view.v1.schema.json` | 本机 Skill 更新来源启停与只读视图 | 保存时显式绑定来源；停用请求不携带 URL，只能复用当前有效签名记录；未知、损坏和陈旧记录拒写 | N03 来源调度规格 |
| `local-skill-execution-context-issue.v1.schema.json` / `local-skill-execution-context-revoke.v1.schema.json` | SEC 在线管理请求 | 仅 capAdmin；签发只提交实例、会话、任务和安装 ID，其余可信身份由 daemon 重读；撤销绑定当前 SEC 签名；均要求显式确认 | N05 可信 Skill 执行上下文规格 |
| `openclaw-approval-checkpoint.v1.md` | 受信宿主审批后执行检查点 | 原生 context 协议版本 1、等待 beforeExecute 严格 true；仅一次执行前状态检查，不是签发或原子执行租约 | OpenClaw 配套宿主 v2 集成 |
| `openclaw-held-execution.v1.md` | OpenClaw 审批后的签名执行预留 | 最终参数重查后原子预留；派生独立执行尝试 ID；observation 绑定 reservation；响应丢失进入 uncertain | N06 可信重试规格 |
| `openshell-decision-relay.v2.schema.json` | OpenShell 沙箱到 AgentShield 的无凭据中继 | 每个 pool 槽位使用 `47611..47710` 中独立的 bridge listener；上游仍固定 loopback `47611`；身份、会话、路由与容器绑定保持精确 | 开发规格 §12.9 |
| `openshell-decision-relay.v3.schema.json` | 独立 Qwen 候选决策桥 | 固定候选 namespace 与带 nonce 沙箱名；沿用 v2 的受限 bridge、路由与在线身份复验；v2 保持原合同 | 开发规格 §12.9 |
| `skill-manifest.schema.json` | siq-agent-security Skill 发布清单 | 二进制按 OS × arch 钉 `sha256`；规则包版本 + 公钥；`support_matrix` 按平台 × OS 标 L0–L3，`audit_only` 不得宣称 L2，macOS/Windows 的 L3 必须写 `requires`；`description` ≤60 字符句号结尾；清单本身签名 | ADR-011 D1/D5 |
| `candidate.schema.json` | 发现阶段的智能体候选 | `evidence_ids` 必填（minItems 1）、确认/驳回生命周期；ADR-011 追加 `source_type` 枚举 `skill_dir`（Skill 目录）与 `platform_config`（平台配置存在性，本机 inventory 产出） | §10.2 / §10.5 |
| `evidence.schema.json` | 可验证证据 | `collected_at`、`expires_at`（新鲜度窗口）、`signature`（Edge 签名） | §10.5 |
| `permission-fact.schema.json` | 权限事实 | 五态 `state`（declared/inferred/observed/effective/unknown）、`delegated_user` 委托维度、authority/revision 溯源 | §12.3 |
| `desired-policy.schema.json` | 后端无关的期望策略 | `enforcement_mode` 渐进档位（audit_only/warn/block）、selector、版本与状态 | §14.1 |
| `event-envelope.schema.json` | 领域事件信封 | event_id/type/occurred_at/tenant/environment/actor/payload + integer schema_version | §18.3 |
| `event-envelope-core.schema.json` | 跨域共享身份字段（ENG-03 权威副本） | event_id/type/occurred_at/tenant_id/request_id/payload；与 Document Engine 字节一致 | SIQ_CROSS_REPO_DEVPLAN ENG-03 |
| `intent-contract.schema.json` | 历史 v1 Intent 约束 | 仅保留历史合同；Decision inline Intent 已拒绝 | Trusted Intent V2 |
| `intent-contract.v2.schema.json` | 受信结构化授权 | principal/agent、tool/effect、资源与 JSON Pointer 约束；canonical digest + Ed25519；由管理面签发 | 开发规格 §10 |
| `runtime-action-envelope.schema.json` | 规范化动作 | action_id、tool_call_id、operation/effects、参数摘要；ID 由服务端生成 | 开发规格 §10.1 |
| `connector-protocol.v1.md` | Edge ↔ Connector 受限子进程协议 | NDJSON、op 清单、错误码、负向语料、签名与新鲜度约定 | §26.1 |
| `siq-business-security-event.v1.schema.json` | SIQ 业务系统到本机 AgentShield 的安全事件投影 | 身份仅保留域分离 SHA-256 引用；授权/模型只保留摘要；无凭据、提示词、回复与业务数据库记录 | 标杆方案 EN-01 |

控制面以 `apps/control-api/app/tests/test_schema_contracts.py` 守护示例与实现方字段同步：schema 示例校验 + 实现方字段一致性，任何一侧漂移即测试失败。ADR-011 四份合同的每条 `if/then` 不变量在该文件各有一条负向测试。

### 本机门禁四合同的数据流

```
已签名发行包：SKILL.md → skill-manifest（清单签名与二进制哈希）→ 二进制
  inventory ──► candidate + evidence（既有合同）
  admit     ──► admission（declared_facts ⊂ permission-fact 语义，state 恒为 declared）
  grant     ──► grant（facts 五态；effective 只能来自后端读回）+ desired-policy 引用
  serve     ──► receipt（哈希链 + Ed25519；平台适配器与模型无签名密钥）
```

开发目录 `skills/siq-agent-security/` 不附发行清单，bootstrap 缺清单时拒绝启动；源码调试从自建 Go 程序开始，不绕过发行验签。详见[源码与发行边界](../../docs/skill-source-release-boundary-20260919.md)。

Go 实现（`apps/agentshield/`）与 Python 实现（control-api）共用本目录 schema 与同一套语料；`engine.name` 字段区分双实现，一致性测试以此比对。

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

仓库当前有 12 个 Go Connector：hermes、directory、openclaw、docker、process、systemd、kubernetes、mcp、piagent、workbuddy、dify、siq。各自采集对象、测试与限制统一见 [Connector README](../../connectors/README.md)；本地选择和远程注册能力的差异见 [Edge README](../../edge/agent/README.md)。

Docker 已有分类与候选输出测试；这不自动补齐全部恶意输入/超时等负向。所有 Connector 都须按协议分别验证 scope、秘密字段、输出大小与失败响应，不能因共享协议而继承其他模块验收。

## Enforcement Adapter 合同

合同定义见设计文档 §15.3（OpenShell Adapter）与 §16.2（Runtime Adapter）。首版实现位于 `apps/control-api/app/adapters/openshell/`（contracts / base / policy_compiler / fake_backend / client / cli_backend）：

- **FakeBackend 契约测试**覆盖：能力探测、revision 冲突、静态 generation、正负验证、回滚、unsupported 显式标记；
- **`openshell-cli` 后端**：已在 OpenShell v0.0.104 真实网关实测"审批 → `policy set` → 读回验证 → effective"闭环（含网络策略热更新，见 [`docs/control-plane.md`](../../docs/control-plane.md) 与[兼容说明](../../docs/compatibility.md)）；该企业阶段记录将正式迁移（v0.0.83 → v0.0.104）列为 canary 窗口，不作为个人端当前后端版本声明，runbook 见[迁移说明](../../docs/openshell-v083-to-v0104-migration.md)；
- 独立进程形态的 Enforcement Adapter 仍为规划；当前仓库没有 `adapters/enforcement/` 实现目录，应从上述实际控制面后端或 [Go OpenShell](../../apps/agentshield/internal/openshell/) 阅读，不能把规划路径当成可用组件。

## 与实现的对应关系（如实核对）

- `desired-policy.enforcement_mode`：实现已落地——只允许升级（audit_only → warn → block），降级必须走 high_risk 变更单并审批（`apps/control-api/app/routers/policies.py`）；**已知限制**：openshell-cli 执行后端当前仅支持 `block` 档，`audit_only`/`warn` 策略在部署时返回 422（`openshell_cli_mode_unsupported`），待后端支持后方可实际部署；
- `permission-fact.delegated_user` 与五态 `state`：Edge 上传的 `permission_facts`（`EdgePermissionFactIn`）与 schema 字段一一对应；`effective` 状态仍只允许控制面派生（模型/Edge 上传不得声明 effective）；
- **重叠冲突语义（overlap）**：定义于设计文档 §12.4（deny-overrides 组合、selector 冲突编译期报错）；实现以编译期静态校验起步，显式冲突输出待补，本目录暂不提供对应 schema 字段——变更前先立项升版。


V2 Go 输出与固定向量位于 `apps/agentshield/testdata/contracts/intent-contract.v2.*.json`，由
`apps/control-api/app/tests/test_intent_v2_contracts.py` 独立验证规范化字节、digest 和签名。
JSON Schema 负责结构；RE2 可编译性、时间窗顺序、证据存在性和 digest/signature 完整性由 Go 运行时校验，不能仅凭 schema 通过就视为可信授权。

绑定撤销：[请求 schema](intent-binding-revoke-request.v1.schema.json)、[签名记录 schema](intent-binding-revocation.v1.schema.json)。管理面撤销为追加不可变记录；原绑定保留，运行时不得回退 unbound。并发与恢复语义见开发规格的绑定撤销增量。

审批后执行采用签名预留：`hold-execution-reserve/v1` 只允许决策凭据申请一次执行，后续读取
`hold-execution-status/v1` 无法证明工具是否启动时必须返回 `uncertain`。管理员核对外部系统后可提交
`hold-execution-reconcile/v1`，仅把“已发生/未发生”写入签名链；该操作不会重新启用旧预留或直接调用工具。


## 如何理解跨层合同

OpenShell 已登记网关只读选择使用 `local-openshell-gateways/v1`、
`local-openshell-gateway-select/v1`、`local-openshell-gateway-targets/v1`、
`local-openshell-gateway-inspect/v1` 和 `local-openshell-gateway-inspection/v1`。
选择 ID 与配置指纹必须由当前本机登记清单解析；请求不能提供任意网关 URL。沙箱清单
和策略读回嵌套现有 v1 合同，保持 `started_gateway=false` 与
`enforcement_verified=false`。选择仅影响查看范围，不修改原生 active gateway、
运行时执行连接或权限。清单失败与空清单分别表达，登记变化时旧选择拒绝。

模型连接与回答检查使用独立的 `local-model-connections/v1`、
`local-model-connection-check/v1`、`local-model-connection-result/v1` 和
`local-model-inference-create/v1`、`local-model-inference-record/v1`、
`local-model-inference-latest/v1`。模型列表匹配不等于实际回答通过；回答测试仅发送固定
公开文本，不执行工具、不改变模型配置或权限。测试以 request_id 在当前服务会话内
去重，刷新读取同一记录；不确定结果不自动重试，配置变化使历史结果失效，记录不跨
服务重启保存。Go 实际输出样例在 `apps/agentshield/testdata/contracts/`，Python Schema
与前端均消费这些样例。具体网络边界与有效期见开发规格 §3 的模型发现增量。

| 层次 | 解决的问题 | 不能据此推导的结论 |
| --- | --- | --- |
| Admission / Grant | 内容检查与明确批准的权限包络 | 准入通过不等于安装、加载或保护 |
| Intent / Provenance / SEC | 当前动作、参数来源和已验证 Skill 执行归属 | Schema 合法不等于签名可信；名称相同不等于身份相同 |
| Hold / Reservation | 批准后最终复验与唯一执行尝试 | approved 不等于已执行；uncertain 不等于没有副作用 |
| Receipt / Effect / Completion | 决策、执行报告、观察材料与任务要求关联 | 签名不认证外部信任根；工具自报成功不等于实际完成 |

开发入口为 [Go 运行时](../../apps/agentshield/README.md)、[控制面](../../apps/control-api/README.md)和[适配器](../../adapters/runtime/README.md)。合同测试在 `apps/control-api` 下执行 `uv run pytest app/tests/test_schema_contracts.py app/tests/test_intent_v2_contracts.py`；改字段还需运行各生产方/消费方对应测试。不能用文档示例替代服务端的签名、时效、撤销和资源复验。

### Hermes 按请求宿主身份（E116）

管理端通过 `local-runtime-request-issuer-create/v1` 显式登记固定企业 scope 和时限的宿主许可，
返回 `local-runtime-request-issuer/v1`。宿主使用根 Runtime Bearer 提交
`local-runtime-request-identity-create/v1`，返回 `local-runtime-request-identity-issued/v1`；
其中 identity 是公开 Summary，不能包含 credential_hash 或签名。私有发行记录使用
`local-runtime-identity/v3`，沿用原 Grant，不改变 v1/v2 身份合同。

`local-runtime-request-identity-cancel/v1` 与 `local-runtime-request-identity-cancelled/v1`
覆盖已发行及尚未发行请求的不可逆取消。请求、执行摘要、期限固定；响应丢失重试不得
延长期限或生成第二身份。上述 HTTP 路由仅在宿主开放，均不属于 sandbox relay 白名单。
研究 API 的主体/业务授权核验仍由研究仓拥有；这些合同不替代企业 IAM 或业务审批。

`local-adapter-instances/v3` 用于显式 `include_projects=true` 的 Hermes 实例读取，
保留 v1 默认范围及 v2 WorkBuddy 合同；新增 `registered_project` 来源。项目登记只扩大
明确位置的只读发现范围，安装、运行身份与权限仍需原接口的独立预览、确认和校验。
