# 合同包（packages/contracts）

本目录是产品对外与对内合同的**事实源**。变更必须升 schema 版本，并同步所有实现方。

## Schema 清单

| 文件 | 内容 | 对应设计文档 |
| --- | --- | --- |
| `candidate.schema.json` | 发现阶段的智能体候选 | §10.2 / §10.5 |
| `evidence.schema.json` | 可验证证据 | §10.5 |
| `permission-fact.schema.json` | 权限事实（含 delegated_user 委托维度） | §12.3 |
| `desired-policy.schema.json` | 后端无关的期望策略（含 enforcement_mode） | §14.1 |
| `event-envelope.schema.json` | 领域事件信封 | §18.3 |

## Connector 子进程协议 v1

Connector 是运行在 Edge Agent 侧的多语言插件（设计文档 §26.1：版本化 gRPC 或受限子进程协议）。首版采用**受限子进程协议**：Edge 以子进程方式调用 Connector，stdin/stdout 交换 NDJSON，每行一条消息。

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
4. 每批次 `evidence` 必须被本批次至少一个 `candidate.evidence_ids` 引用；
5. Connector 版本升级必须通过兼容与安全测试（负向：恶意配置/超大文件/符号链接逃逸）。

## Enforcement Adapter 合同

见设计文档 §15.3（OpenShell Adapter）与 §16.2（Runtime Adapter）。首版实现位于 `adapters/enforcement/openshell/`，Phase 3 交付。
