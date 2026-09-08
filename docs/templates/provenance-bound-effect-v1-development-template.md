下面这份可以**直接原样交给 Codex**。我已经按最新 `main` 的 Trusted Intent V2 完成度重新收敛范围，避免 Codex 重做已经完成的东西。

# SIQ Agent Security — Provenance-Bound Effect Security V1

## 0. 角色与执行要求

你现在是本项目的：

* Senior Staff AI Security Engineer
* Agent Runtime Security Engineer
* Go / Python / TypeScript Full-stack Engineer
* Systems Security Engineer

Repository:

`maoyadongsh/siq-agent-security`

当前已知基线：

```text
main
d001c4d2c1b7a1230604e8b2ecf813a39deb251c
```

提交：

```text
agentshield: verify legacy optional compatibility and finalize V2 audit
```

开始前必须：

```bash
git fetch --all --prune
git checkout main
git pull --ff-only
git status
git log -5 --oneline
```

如果 `main` 已领先于上述 SHA：

1. 以实际最新 `main` 为基线；
2. 先检查新增实现；
3. 不覆盖、回退或重复最新功能；
4. 在最终报告中记录实际基线 SHA。

创建独立开发分支：

```text
codex/provenance-bound-effect-v1
```

不要直接向 main 写提交。

---

# 1. 当前已经实现的能力：禁止重复开发

当前项目已经完成 Trusted Intent Authority & Action Binding V2 的核心闭环。

不要重写：

```text
Admission
Grant
Signed immutable Intent
Signed Session Binding
Intent Binding Revocation
Tool / Operation / Effect separation
Resource constraints
JSON Pointer parameter constraints
Runtime allow / deny / hold / redact
Stateful taint
Lethal trifecta
Action ID
TaskSeq
ParentActionID
Decision Receipt
Decision → Observe correlation
Hold approval
Hold status
OpenClaw execution-before-recheck integration
Hermes / OpenClaw / CodeBuddy adapters
Receipt hash chain
Ed25519 signing
Crash recovery
Legacy optional compatibility
OpenShell integration
Enterprise Control Plane
```

不要创建第二个 Runtime Reference Monitor。

不要重新设计一套签名格式。

继续复用：

```text
internal/canon
internal/signing
internal/intent
internal/runtimeaction
internal/receipt
internal/state
packages/contracts
```

---

# 2. 当前技术阶段

现有主授权链大致是：

```text
Human / Admin Authority
        ↓
Signed IntentContract
        ↓
Signed Session Binding
        ↓
Grant
        ↓
RuntimeAction
        ↓
Grant ∩ Intent ∩ RuntimeState
        ↓
allow / deny / hold / redact
        ↓
Signed Decision Receipt
        ↓
Platform Execution
        ↓
Correlated Observation
```

这一阶段已经完成。

本轮目标不是继续强化 Intent。

本轮目标是把系统升级为：

```text
Identity
   ↓
Intent
   ↓
Authority
   ↓
Trusted Context
   ↓
Parameter Provenance
   ↓
Runtime Behavior
   ↓
Execution
   ↓
Effect Evidence
```

核心目标公式：

```text
Effective Runtime Authority
=
Grant
∩ Intent
∩ Trusted Context
∩ Parameter Provenance
∩ Runtime State
```

之后：

```text
Authorized Action
→ Execution
→ Effect Evidence
```

---

# 3. 本轮最高层安全不变量

必须把以下规则写进代码、合同和测试，而不是只写文档。

## INV-1

Agent / LLM / MCP / Tool / Web / Memory 内容：

```text
are DATA
```

不是：

```text
AUTHORITY
```

---

## INV-2

调用者不能通过自由字段声明：

```text
USER
TRUSTED_IAM
trusted
authoritative
```

然后获得更高权限。

---

## INV-3

来源标签必须和来源 Authority 分离：

```text
SourceType
≠
TrustLevel
≠
Authority
```

---

## INV-4

没有可信来源证据时：

```text
UNKNOWN
```

不能猜。

---

## INV-5

关键参数的合法性由：

```text
Value Constraint
+
Provenance Constraint
```

共同决定。

---

## INV-6

Tool Result：

```json
{"success": true}
```

不能直接证明真实世界 Effect 成功。

---

## INV-7

Authority 完整性失败与普通 Policy violation 必须分层。

无效 Authority：

```text
MUST NOT
```

因为：

```text
audit_only
warn
```

而变成真实执行许可。

---

# 4. 本轮工作范围

本轮必须完成四个核心 Workstream：

```text
A. Authority Hard Gate + Trusted Context

B. Parameter-Level Provenance MVP

C. EffectEvidence V1

D. Runtime Security Benchmark V1
```

同时进行必要的：

```text
runtimeaction semantic refactor
schema
tests
docs
CI
```

---

# 5. 本轮明确不做

不要扩大 Scope 到：

### 不做

完整 Managed Linux production deployment。

只允许做接口准备或最小 spike，不作为本轮 DoD。

### 不做

完整 Multi-Agent Delegation DAG。

### 不做

Neural Taint。

### 不做

LLM-based final authorization。

### 不做

通用 Behavioral Sandbox Engine。

### 不做

新的微服务。

### 不做

Graph Database。

### 不做

大规模 UI 重构。

### 不做

把所有 Web/Memory/Tool 来源一次覆盖。

本轮 Provenance 的真实优先场景：

```text
MCP + explicit trusted structured sources
```

---

# 6. Workstream A — Authority Hard Gate

## 6.1 当前问题

当前 Engine 的 Authority failure：

例如：

```text
intent_binding_missing
intent_expired
intent_signature_invalid
intent_binding_revoked
intent_agent_mismatch
intent_task_mismatch
```

会先生成：

```text
deny
```

然后可能被：

```text
audit_only / warn
```

转换为：

```text
actual allow
advisory deny
```

这会混淆：

```text
Authority invalid
```

和：

```text
Policy would deny
```

---

# 7. 建立 Authorization Decision 两阶段模型

重构 Runtime Decision：

```text
Stage 1 — Authority Gate

Stage 2 — Runtime Policy Evaluation
```

建议结构：

```go
type AuthorityResult struct {
    Valid      bool
    ReasonCode string
    Reason     string
}

type PolicyResult struct {
    Action     string
    ReasonCode string
    Reason     string
}
```

最终：

```text
Authority invalid
→ HARD DENY

Authority valid
→ evaluate runtime policy
→ apply audit/warn/block semantics
```

---

# 8. Hard Gate reason codes

至少包括：

```text
intent_binding_missing
intent_not_found
intent_digest_mismatch
intent_signature_invalid
intent_expired
intent_agent_mismatch
intent_principal_mismatch
intent_task_mismatch
intent_binding_revoked
intent_binding_revocation_invalid
intent_downgrade_attempt

trusted_context_invalid
trusted_context_expired
trusted_context_scope_mismatch

provenance_authority_invalid
```

这些不能被：

```text
warn
audit_only
```

转换成真实 allow。

---

# 9. Enforcement Mode 只处理 Policy Result

例如：

```text
grant_scope_violation
session_taint_violation
lethal_trifecta
rule_violation
```

可以根据现有产品兼容需求：

```text
audit_only
warn
block
```

处理。

但必须明确：

```text
Authority Gate
```

发生在：

```text
Enforcement Mode
```

之前。

---

# 10. Receipt Schema 升级

不要破坏历史 Receipt。

建议新增 optional 字段或新 schema version：

```json
{
  "authority_status": "valid|invalid|unbound_legacy",

  "authority_reason_code": "...",

  "policy_action": "allow|deny|hold|redact",

  "effective_action": "allow|deny|hold|redact",

  "advisory_action": "..."
}
```

其中：

```text
effective_action
```

才是真实执行结果。

---

# 11. Required / Optional 兼容矩阵

必须覆盖：

| intent                                          | mode       | missing/invalid authority |
| ----------------------------------------------- | ---------- | ------------------------- |
| required                                        | block      | DENY                      |
| required                                        | warn       | DENY                      |
| required                                        | audit_only | DENY                      |
| optional + never bound                          | block      | legacy Grant              |
| optional + never bound                          | warn       | legacy Grant              |
| optional + never bound                          | audit      | legacy Grant              |
| optional + previously bound but missing/revoked | any        | DENY                      |

最后一条不能回退。

---

# 12. Workstream A2 — 消除 `context.cwd` 的隐式授权能力

## 当前问题

Runtime 当前读取：

```text
req.Context["cwd"]
```

并允许路径：

```text
inside cwd
```

获得授权。

调用方 Context 不能成为 Authority。

---

# 13. 新规则

`req.Context`：

```text
Observational only
```

不得直接扩大文件权限。

删除或禁用：

```text
caller supplied cwd
→ grant path allow
```

语义。

---

# 14. Workspace Authority

如产品仍需要“允许当前工作区”功能：

必须来自受信来源。

优先方案：

在 Signed Intent / Grant 中表达：

```json
{
  "domain": "filesystem",
  "operator": "prefix",
  "value": "/trusted/workspace"
}
```

不要从：

```text
context.cwd
```

隐式推导。

---

# 15. ContextAssertion V1

新增合同：

```text
packages/contracts/context-assertion.v1.schema.json
```

用途不是一次解决所有 Context Attestation。

V1 只建立可信上下文基本结构：

```json
{
  "schema_version": "context-assertion/v1",

  "assertion_id": "...",

  "issuer_id": "...",

  "subject": {
    "platform": "...",
    "session_id": "...",
    "agent_id": "..."
  },

  "task_id": "...",

  "claims": {
    "workspace_root": "..."
  },

  "issued_at": "...",
  "expires_at": "...",

  "request_binding": "...",

  "signing_schema": "...",
  "signature": "..."
}
```

---

# 16. ContextAssertion 限制

第一版只允许少量 claim：

```text
workspace_root
```

不要现在加入：

```text
MFA
role
tenant
device_trust
geo
```

这些以后再做。

---

# 17. ContextAssertion 信任来源

只有：

```text
Admin / trusted host attestor
```

可以签发。

Decision client 不能签发可信 ContextAssertion。

Adapter 自报：

```text
context.cwd
```

仍可进入日志，但：

```text
trust = observational
```

不得授权。

---

# 18. Workstream B — Parameter-Level Provenance

这是本轮核心研究/产品升级。

新增独立 package：

```text
apps/agentshield/internal/provenance/
```

建议结构：

```text
provenance/
  types.go
  validate.go
  store.go
  issuer.go
  resolve.go
  matcher.go
  digest.go
```

不要把全部代码写进：

```text
receipt.Engine
```

---

# 19. Provenance 基本模型

新增：

```text
packages/contracts/provenance-assertion.v1.schema.json
```

推荐：

```json
{
  "schema_version": "provenance-assertion/v1",

  "provenance_id": "...",

  "source": {
    "type": "MCP",
    "source_id": "...",
    "trust": "untrusted"
  },

  "scope": {
    "platform": "...",
    "session_id": "...",
    "agent_id": "...",
    "task_id": "..."
  },

  "content_digest": "...",

  "parents": [],

  "derivation": "direct",

  "issued_at": "...",
  "expires_at": "...",

  "issuer": "...",

  "signing_schema": "...",
  "signature": "..."
}
```

---

# 20. Source Type

冻结 V1 taxonomy：

```text
USER
SYSTEM

TRUSTED_IAM
TRUSTED_DATABASE

MCP
WEB
TOOL
MEMORY
AGENT

SECRET
CONFIDENTIAL

UNKNOWN
```

禁止动态字符串无限扩展。

---

# 21. Trust Level

独立字段：

```text
authoritative
trusted
untrusted
unknown
```

不要根据 SourceType 自动推断。

例如：

```text
MCP
```

默认：

```text
untrusted
```

但未来受信企业 MCP 可以由明确 issuer 改变。

---

# 22. 谁可以签什么 Trust

这是核心安全规则。

Decision client 可以报告：

```text
MCP
WEB
TOOL
AGENT
UNKNOWN
```

但最多只能产生：

```text
untrusted
unknown
```

Decision client：

```text
MUST NOT
```

签发：

```text
USER + authoritative

TRUSTED_IAM + authoritative

TRUSTED_DATABASE + trusted
```

---

# 23. Trusted Provenance Issuer Registry

建立管理面可配置：

```text
TrustedSourceIssuer
```

字段建议：

```text
issuer_id
public_key / local issuer reference

allowed_source_types
max_trust_level

scope
expires_at
revoked_at
```

第一版本机模式可以由：

```text
local-admin
```

管理。

企业模式以后由 Control Plane 下发。

---

# 24. Provenance 不能证明内容为真

文档必须明确：

签名 Provenance 只能证明：

```text
issuer X asserted source Y
```

不能证明：

```text
the data itself is objectively true
```

例如：

```text
TRUSTED_DATABASE
```

也可能包含脏数据。

---

# 25. Parameter Provenance Binding

新增：

```text
packages/contracts/parameter-provenance.v1.schema.json
```

推荐：

```json
{
  "parameter_path": "/recipient",

  "provenance_refs": [
    "prov-..."
  ]
}
```

Runtime Request 可以携带：

```text
parameter_provenance
```

但里面不能出现自由：

```text
source_type=USER
trust=authoritative
```

只能引用：

```text
server-verifiable provenance_ref
```

---

# 26. Parameter Provenance Resolution

Engine：

```text
parameter path
   ↓
provenance_ref
   ↓
lookup
   ↓
signature validation
   ↓
scope validation
   ↓
expiry validation
   ↓
issuer authority validation
   ↓
resolved provenance
```

任何：

```text
missing
invalid
expired
wrong task
wrong session
wrong agent
unknown issuer
forged signature
```

都不能被当成可信 Provenance。

---

# 27. IntentContract V3

不要静默改变 Intent V2 安全语义。

新增：

```text
packages/contracts/intent-contract.v3.schema.json
```

V2 继续 dual-read / verify。

V3 新增：

```text
provenance_constraints
```

例如：

```json
{
  "parameter_path": "/recipient",

  "allowed_source_types": [
    "USER",
    "TRUSTED_IAM"
  ],

  "minimum_trust": "trusted"
}
```

---

# 28. Provenance Constraint

第一版支持：

```text
allowed_source_types
minimum_trust
required
```

不要增加复杂 query language。

---

# 29. High-Impact Parameter

在 runtimeaction 中增加：

```text
HighImpactParameters
```

不要在 Provenance Engine 里重新维护 Tool 语义。

第一版至少覆盖：

```text
recipient
destination_host
url
filesystem_target
database_scope
credential_ref
deployment_target
repo
branch
command
account
identity
```

具体 JSON Pointer 应由：

```text
RuntimeAction Descriptor
```

提供。

---

# 30. RuntimeActionDescriptor 重构

当前 Tool 语义同时分散于：

```text
runtimeaction.Normalize
receipt.Engine
egressTools
shellTools
regex extraction
```

本轮做一次受控重构。

增加：

```go
type Descriptor struct {
    Tool       string
    Operation  string
    Effects    []string
    Resources  []Resource

    Egress     bool
    Mutating   bool
    ShellLike  bool

    HighImpactParameterPaths []string
}
```

入口：

```go
runtimeaction.Describe(tool, params)
```

---

# 31. 所有安全模块消费同一个 Descriptor

以下组件不得自己再重新分类 Tool：

```text
Grant evaluator
Intent evaluator
Taint evaluator
Trifecta evaluator
Provenance evaluator
Receipt builder
```

必要的 regex 可以存在。

但集中到：

```text
runtimeaction
```

内部。

---

# 32. Shell 仍保持 Conservative

对于：

```text
bash
sh
python
node
powershell
```

必须保持：

```text
process.exec
+
unknown
```

除非底层真正拥有独立 effect telemetry。

不要因为解析到 curl 就认为所有 Effect 已完全知道。

---

# 33. Workstream B2 — MCP Provenance MVP

本轮 Provenance 的第一个真实外部来源：

```text
MCP
```

不要一次覆盖所有来源。

---

# 34. MCP Provenance 生命周期

设计：

```text
MCP Server
   ↓
server identity / endpoint identity
   ↓
tool identity
   ↓
tool result
   ↓
Provenance Assertion
   ↓
LLM / transformation
   ↓
parameter provenance refs
   ↓
Runtime Action
```

---

# 35. MCP 默认规则

所有 MCP 内容默认：

```text
SourceType = MCP
Trust = untrusted
```

除非受信 issuer 明确证明其他等级。

MCP：

```text
tool name
description
annotations
result
```

本身不能扩大 Authority。

---

# 36. 不做完整语义传播

第一版不要声称可以自动回答：

```text
“模型把 MCP 内容总结了三次以后，
某个 token 到底受哪个字符影响”
```

这一版只支持：

```text
explicit / deterministic lineage
```

例如：

```text
direct
transformed
aggregated
unknown
```

---

# 37. Derivation

冻结：

```text
direct
transformed
aggregated
unknown
```

如果无法可靠跟踪：

```text
unknown
```

不要猜。

---

# 38. Security Rule — Untrusted High-Impact Control

新增核心 deterministic invariant：

```text
UNTRUSTED_EXTERNAL
cannot control
HIGH_IMPACT_PARAMETER
unless explicitly authorized by Intent.
```

实现不依赖 LLM classifier。

---

# 39. 示例

Intent：

```text
send report to Alice
```

约束：

```text
/recipient
allowed_source_types:
    USER
    TRUSTED_IAM

minimum_trust:
    trusted
```

MCP：

```text
Alice = attacker@example.com
```

来源：

```text
MCP / untrusted
```

结果：

```text
DENY
reason_code = provenance_source_not_allowed
```

---

# 40. 同值不同来源测试

必须测试：

```text
recipient = alice@company.com
```

来源 A：

```text
USER / authoritative
```

→ allow

来源 B：

```text
MCP / untrusted
```

→ deny

这证明系统真正实现：

```text
Value + Provenance
```

授权。

---

# 41. Provenance reason codes

至少：

```text
provenance_missing
provenance_not_found
provenance_signature_invalid
provenance_expired
provenance_scope_mismatch
provenance_issuer_untrusted
provenance_source_not_allowed
provenance_trust_insufficient
provenance_derivation_unknown
provenance_capacity
```

---

# 42. Provenance 容量

必须 bounded。

建议候选初始值：

```text
max nodes per task: 1024
max edges per task: 4096
max parents per node: 32
max traversal depth: 64
```

这些数值是：

```text
initial engineering defaults
```

不是产品 SLA。

---

# 43. Provenance 容量耗尽

不能：

```text
drop suspicious nodes
→ assume clean
```

应：

```text
provenance_capacity
→ fail closed for actions requiring provenance
```

普通不依赖 Provenance 的 legacy task 可按 profile 继续。

---

# 44. Provenance 存储

保持：

```text
append-only / immutable
```

优先内容摘要和引用。

不要长期保存全部：

```text
MCP raw result
Web raw page
Tool raw result
```

防止泄密和无限增长。

---

# 45. Workstream C — EffectEvidence V1

当前：

```text
Observe
```

证明：

```text
platform/tool reported a result
```

不等于：

```text
real-world effect independently verified
```

本轮建立独立 EffectEvidence。

---

# 46. EffectEvidence Schema

新增：

```text
packages/contracts/effect-evidence.v1.schema.json
```

推荐：

```json
{
  "schema_version": "effect-evidence/v1",

  "effect_evidence_id": "...",

  "action_id": "...",
  "decision_receipt_id": "...",

  "effect_type": "file.write",

  "resource_ref": "...",

  "execution_state": "completed",

  "source": {
    "type": "host_observer",
    "source_id": "...",
    "independence": "independent"
  },

  "coverage": "partial",

  "result": "expected",

  "evidence_digest": "...",

  "observed_at": "...",

  "signing_schema": "...",
  "signature": "..."
}
```

---

# 47. 不设计单一“安全等级”

不要简单实现：

```text
reported < observed < enforcement_verified
```

改用多维属性。

至少：

```text
execution_state

source_type

independence

coverage

result
```

---

# 48. execution_state

冻结：

```text
requested
started
completed
failed
unknown
```

---

# 49. source_type

第一版：

```text
tool_report
host_observer
openshell
provider_audit
test_oracle
unknown
```

---

# 50. independence

```text
self_reported
host_independent
external_independent
unknown
```

---

# 51. coverage

```text
full
partial
unknown
```

---

# 52. result

```text
expected
unexpected
conflicting
unknown
```

---

# 53. Tool Result 只产生 Observation

现有：

```text
/v1/observe
```

继续存在。

Adapter Tool Result：

```text
MUST NOT
```

直接产生：

```text
external_independent
full
expected
```

级别的证据。

---

# 54. EffectEvidence API

增加独立接口，例如：

```text
POST /v1/effect-evidence
GET  /v1/effect-evidence/{id}
GET  /v1/actions/{action_id}/effect-evidence
```

普通 decision token：

不得提交：

```text
external_independent
```

可信 Effect Observer 需要独立 capability。

---

# 55. Effect Observer Capability

在本机 Server Auth 中新增能力：

```text
capEffectObserve
```

与：

```text
capDecision
capAdmin
```

分离。

第一版可以通过受信本地 observer token / management provision。

不要复用：

```text
decision token
```

作为独立效果证明权威。

---

# 56. File Effect MVP

第一种真正支持的 Effect：

```text
file.write
```

实现 host-side observer。

最小证据：

```text
resolved path / resource digest
pre-existing?
post-existing?
post digest
size
mtime
```

注意：

如果 observer 与 Agent 同 UID：

只能标：

```text
host_independent
```

不能宣称：

```text
malicious-agent-proof
```

---

# 57. Network Effect MVP

第二种：

```text
network.request
```

本轮不要尝试普适互联网验证。

只做：

```text
controlled test endpoint
```

用于 benchmark。

记录：

```text
scheme
host
port
resolved target
request id
server-side received event
```

只有测试服务器自身日志可作为：

```text
external_independent
```

---

# 58. Network 重定向测试

Benchmark 必须覆盖：

```text
approved host
→ HTTP redirect
→ unapproved host
```

区分：

```text
requested destination
final destination
```

---

# 59. Fake Tool Success

必须有场景：

Tool 返回：

```json
{
  "success": true
}
```

但独立 oracle：

```text
no effect
```

最终：

```text
Observation = success report

EffectEvidence = absent / conflicting
```

不能标记 task complete。

---

# 60. EffectEvidence 与 Receipt 链

EffectEvidence 必须引用：

```text
action_id
decision_receipt_id
```

并验证前置 Action。

不能为：

```text
denied action
```

建立：

```text
expected completed
```

类型成功 Effect。

若独立 observer 真的观察到 denied effect：

这是：

```text
SECURITY INCIDENT
```

而不是普通成功。

新增：

```text
unauthorized_effect_observed
```

reason / finding。

---

# 61. Completion 不在本轮完全实现

本轮只增加：

```text
CompletionStatus
```

最小模型：

```text
verified
incomplete
conflicting
unknown
```

不要做完整业务 Workflow Engine。

---

# 62. CompletionStatus API

建议：

```text
GET /v1/tasks/{task_id}/completion
```

根据：

```text
Intent
Actions
Observations
EffectEvidence
```

给出结构化结果。

不能由模型写：

```text
completed=true
```

---

# 63. CompletionStatus 第一版规则

如果 Intent 没定义 Effect verification requirement：

```text
unknown / not_required
```

如果定义：

```text
required_effect = file.write
```

且存在匹配独立证据：

```text
verified
```

没有证据：

```text
incomplete / unknown
```

冲突：

```text
conflicting
```

---

# 64. Workstream D — Runtime Security Benchmark V1

当前工程测试强。

但研究 benchmark 必须独立建立。

新目录：

```text
benchmarks/runtime-security/
```

不要继续塞入：

```text
skills/siq-agent-security/evals/evals.json
```

---

# 65. Benchmark Endpoint Model

正式采用：

```text
D0 Semantic Acceptance

D1 Unsafe Commitment

D2 Action Attempt

D3 Tool Materialization

D4 Observed Effect

D5 Independently Verified Effect
```

注意：

D0/D1 第一版可以人工 fixture / optional offline evaluator。

D2–D5 必须尽可能确定性。

---

# 66. Benchmark Scenario Contract

新增：

```text
benchmarks/runtime-security/scenario.schema.json
```

示例：

```json
{
  "id": "prov-recipient-mcp-001",

  "task": {},

  "attack": {},

  "expected": {
    "d2": true,
    "d3": false,
    "reason_code": "provenance_source_not_allowed"
  }
}
```

---

# 67. Benchmark 必须覆盖的攻击

至少：

```text
recipient injection

destination host injection

filesystem resource hijacking

forged cwd

forged USER provenance

forged TRUSTED_IAM provenance

MCP untrusted parameter control

missing provenance

expired provenance

wrong-task provenance replay

cross-session provenance replay

revoked Intent

approval revoked before execution

fake tool success

denied action with observed effect

HTTP redirect

conflicting effect evidence

provenance capacity exhaustion
```

---

# 68. Benign Controls

每一个攻击类别必须至少存在一个正常任务对照。

例如：

```text
trusted USER recipient
trusted IAM recipient
approved MCP content used only in non-high-impact message body
approved filesystem path
approved network endpoint
```

不能通过：

```text
deny everything
```

取得“安全”。

---

# 69. Benchmark Metrics

至少：

```text
False Allow Rate

False Deny Rate

Benign Task Completion Rate

Intent Violation Block Rate

Provenance Violation Block Rate

Resource Hijacking Block Rate

Unauthorized Effect Rate

Unknown Effect Rate

Manual Approval Rate
```

按 D0–D5 单独统计。

---

# 70. 不得错误计算 ASR

如果 D5 没有独立 Oracle：

该样本：

```text
must not
```

进入 D5 分母。

输出：

```text
not evaluated
```

而不是：

```text
attack failed
```

---

# 71. Performance Metrics

新增分阶段延迟：

```text
authority validation
intent lookup
context validation
provenance resolution
runtime action normalization
policy evaluation
receipt append/fsync
effect evidence processing
```

报告：

```text
P50
P95
P99
```

不要制定虚构 SLA。

---

# 72. Workstream E — Threat Model

更新：

```text
docs/threat-model.md
```

新增至少：

```text
T27 Forged Runtime Context

T28 Provenance Forgery

T29 Provenance Replay

T30 Provenance Laundering

T31 High-Impact Parameter Hijacking

T32 Fake Tool Success

T33 Unauthorized Effect Despite Denial

T34 Effect Evidence Forgery

T35 Evidence Coverage Gap
```

每条：

```text
Threat
→ Control
→ Negative Test
→ Residual Risk
```

---

# 73. Provenance Laundering Threat

必须明确：

攻击者不能通过：

```text
MCP untrusted
↓
Agent says "I verified it"
↓
becomes USER/trusted
```

来源传播不允许自动升级 Trust。

规则：

```text
Trust(output)
<=
max authority legitimately introduced by trusted transformation
```

第一版：

所有普通 Agent transform：

```text
cannot increase trust
```

---

# 74. Aggregation Rule

例如：

```text
USER authoritative
+
MCP untrusted
↓
aggregated
```

默认结果：

```text
untrusted
```

或至少：

```text
mixed / insufficient
```

不要采用最高信任来源覆盖最低信任来源。

第一版简单规则：

```text
effective trust = minimum(parent trust)
```

即可。

---

# 75. Transformation Rule

普通：

```text
AGENT transform
```

不得提升：

```text
trust
```

例如：

```text
MCP untrusted
→ LLM summarize
→ still untrusted
```

---

# 76. UNKNOWN Rule

出现：

```text
unknown parent
unknown transformation
missing provenance
```

关键参数：

```text
fail closed / hold
```

普通低影响文本参数：

可以按 Intent 配置决定。

---

# 77. Workstream F — Capability Matrix

更新：

```text
docs/agentshield-capability-matrix-v1.md
```

新增独立能力：

```text
Authority Hard Gate

Context Assertion

Provenance Assertion

Parameter Provenance

MCP Provenance

High-Impact Parameter IFC

EffectEvidence

Independent Effect Oracle

Completion Evaluation
```

状态：

```text
evidenced
unverified
n/a
```

不要新增：

```text
supported
```

除非项目今后单独改变能力政策。

---

# 78. 实现 ≠ 平台证明

例如：

```text
Parameter Provenance core = evidenced

OpenClaw provenance E2E = unverified
```

必须分开。

---

# 79. Workstream G — Adapter 设计

Adapters 必须继续：

```text
thin
```

不要把安全策略复制到 TypeScript/Python Adapter。

Adapter 只负责：

```text
platform event
tool identity
tool call identity
params/result
explicit provenance handles
```

所有 Authority / provenance policy：

```text
AgentShield daemon
```

决定。

---

# 80. Adapter 自报来源的限制

例如 Adapter 说：

```text
source_type = MCP
```

可以记录。

但不能自己声明：

```text
trust = authoritative
```

受信 Trust 必须经服务器 issuer 验证。

---

# 81. OpenClaw Hold Gate 不得退化

必须保留最新：

```text
approvalExecutionRecheckVersion
beforeExecute
current hold-status
final params recheck
```

本轮 Provenance 重构不得让审批 TOCTOU 防御退化。

---

# 82. Intent Binding Revocation 不得退化

必须保留：

```text
signed immutable revocation
```

所有新的 Provenance / Effect API 必须正确处理：

```text
revoked task/authority
```

---

# 83. Workstream H — Enterprise Compatibility Preparation

本轮不实现完整：

```text
Enterprise → Intent issuer
```

但 Contract 必须允许未来 issuer：

```text
local-admin

enterprise-control-plane
```

不要把：

```text
local signing key
```

永久硬编码进数据模型。

---

# 84. Issuer abstraction

建议：

```go
type IssuerID string

type TrustBundle interface {
    ResolveIssuer(...)
    Verify(...)
}
```

当前 local mode 可用：

```text
local canonical Ed25519
```

以后企业模式接：

```text
control-plane trust bundle
```

---

# 85. Workstream I — Security Testing

必须添加以下核心负向测试。

## P-01

伪造：

```text
USER / authoritative
```

由 decision token 提交。

期望：

```text
DENY / invalid provenance authority
```

---

## P-02

合法 MCP provenance：

```text
MCP / untrusted
```

控制：

```text
/recipient
```

Intent 要求 USER/TRUSTED_IAM。

期望：

```text
DENY
provenance_source_not_allowed
```

---

## P-03

同值不同来源。

前文场景。

---

## P-04

Provenance 从 task A replay 到 task B。

期望：

```text
DENY
provenance_scope_mismatch
```

---

## P-05

Provenance 从 session A replay 到 session B。

期望 deny。

---

## P-06

已过期 provenance。

期望 deny。

---

## P-07

Provenance 文件被篡改。

期望：

```text
signature/digest failure
```

---

## P-08

Agent transform：

```text
MCP/untrusted
→ AGENT/transformed
```

不得提升 trust。

---

## P-09

Aggregation：

```text
USER authoritative
+
MCP untrusted
```

不能变 authoritative。

---

## P-10

Missing provenance for required high-impact parameter。

期望：

```text
DENY/HOLD
```

按 Intent 定义。

---

# 86. Context Tests

## C-01 Forged cwd

Request：

```text
context.cwd=/secret
```

Grant/Intent 未授权。

期望：

```text
DENY
```

---

## C-02 Trusted workspace assertion

合法 signed workspace assertion。

期望按 Intent / Grant 正常授权。

---

## C-03 Expired workspace assertion

期望 hard deny。

---

## C-04 Cross-session assertion replay

期望 deny。

---

# 87. Hard Gate Tests

覆盖矩阵：

```text
required × audit
required × warn
required × block
```

以下全部：

```text
invalid authority → effective deny
```

---

# 88. Effect Tests

## E-01 Fake success

Tool：

```text
success=true
```

File 不存在。

EffectEvidence：

```text
no independent evidence
```

Completion：

```text
unknown/incomplete
```

---

## E-02 Real file write

Tool 执行成功。

Host observer 验证 digest。

EffectEvidence：

```text
file.write
completed
host_independent
```

---

## E-03 Denied but effect observed

Decision：

```text
deny
```

测试 fixture 绕过 Reference Monitor 写入文件。

Observer 看到。

结果：

```text
unauthorized_effect_observed
```

不能普通记录为成功。

---

## E-04 HTTP redirect

Intent：

```text
host A
```

最终服务器：

```text
host B
```

Oracle 记录。

期望 Effect mismatch。

---

## E-05 Conflicting evidence

Tool：

```text
success
```

Oracle：

```text
not received
```

结果：

```text
conflicting
```

---

# 89. Concurrency / Recovery

必须测试：

```text
provenance issue + decide concurrency

provenance revoke/expiry + decide

effect evidence duplicate submission

conflicting effect evidence

restart between decision and effect

restart after provenance issue

capacity exhaustion

receipt recovery
```

运行：

```bash
go test -race ./...
```

---

# 90. Schema Tests

每个新 schema：

```text
valid
missing required
additional property
bad id
bad signature
bad digest
bad timestamp
bad source type
bad trust
bad scope
bad parent
capacity invalid
```

必须有正负 fixture。

---

# 91. Cross-language Vectors

为以下建立固定向量：

```text
ContextAssertion
ProvenanceAssertion
EffectEvidence
```

Python 和 Go：

```text
canonical bytes
digest
signature verification
```

必须一致。

---

# 92. Security Boundary — Same UID

所有文档和 capability 必须继续明确：

```text
desktop-same-uid
```

下：

这些签名和 provenance 主要保证：

```text
protocol integrity
audit integrity
logical authority separation
```

不是：

```text
malicious same-UID process isolation
```

不要因为本轮新增签名 provenance 就提升 OS 安全宣称。

---

# 93. Managed Linux 预留

本轮只允许：

```text
interface
ADR
minimal spike
```

例如：

```text
EffectObserver
ContextAttestor
IssuerResolver
```

都不应假设 same UID。

未来可以由：

```text
Unix socket
SO_PEERCRED
different UID
OpenShell
eBPF
```

实现。

但不要本轮完整开发。

---

# 94. Documentation

新增 ADR：

```text
docs/adr/0015-authority-hard-gate.md

docs/adr/0016-parameter-provenance.md

docs/adr/0017-effect-evidence.md
```

编号如仓库实际已有冲突，以最新编号顺延。

---

# 95. ADR — Authority Hard Gate

必须解释：

```text
Authority invalid
≠
Policy advisory
```

为什么：

```text
audit / warn
```

不能放宽：

```text
missing/invalid mandatory authority
```

---

# 96. ADR — Provenance

必须明确：

```text
provenance
≠
truth

signed source assertion
≠
data correctness

source label
≠
authority
```

---

# 97. ADR — Effect

必须明确：

```text
tool result
≠
effect

host observed
≠
malicious-agent-proof

effect evidence
≠
complete coverage
```

---

# 98. README

只增加用户真正需要知道的最小内容。

不要把 README 变成论文。

说明：

```text
Trusted Intent
Provenance experimental
EffectEvidence experimental
```

并明确 evidence level。

---

# 99. 工程结构建议

目标：

```text
internal/
  intent/
  provenance/
  contextassert/
  runtimeaction/
  runtimeauthz/
  receipt/
  effect/
  state/
  server/
```

实际按现有项目调整。

---

# 100. Receipt Engine 重构原则

不要微服务化。

但逐渐把：

```text
Authority
Policy
Provenance
Effect
```

职责拆开。

建议核心流程：

```text
Decide()
    ↓
AuthorityGate
    ↓
RuntimeAction.Describe
    ↓
GrantEvaluator
    ↓
IntentEvaluator
    ↓
ProvenanceEvaluator
    ↓
StatefulRiskEvaluator
    ↓
EnforcementAdapter
    ↓
ReceiptWriter
```

---

# 101. 不允许出现 God Engine 进一步膨胀

如果 `receipt/engine.go` 继续增加大量：

```text
provenance
context
effect
```

逻辑，应重构。

但保持：

```text
same process
same transactional security flow
```

---

# 102. CI

完成后必须通过现有全仓 CI。

至少执行：

```bash
gofmt
go vet ./...
go test ./...
go test -race ./...
govulncheck ./...
```

以及现有：

```text
Control API Ruff
Control API pytest
schema tests
fixed vectors
web tests
web build
edge tests
connector tests
adapter tests
security static checks
supply-chain checks
cross compile
```

---

# 103. 新 CI Job

增加：

```text
runtime-security-contracts
```

或整合现有 CI。

至少跑：

```text
provenance fixed vectors
hard-gate matrix
effect evidence schema
benchmark smoke
```

---

# 104. Benchmark 不允许阻塞每个 PR 的项目

PR：

运行：

```text
small deterministic smoke corpus
```

Nightly：

运行：

```text
larger adversarial corpus
controlled effect oracle
recovery tests
```

---

# 105. CODEOWNERS

如果仓库当前没有：

新增：

```text
.github/CODEOWNERS
```

至少保护：

```text
/packages/contracts/
/apps/agentshield/internal/intent/
/apps/agentshield/internal/provenance/
/apps/agentshield/internal/runtimeaction/
/apps/agentshield/internal/receipt/
/apps/agentshield/internal/server/
/apps/control-api/app/security.py
/.github/workflows/
```

如果无法确定 owner：

使用仓库 owner。

---

# 106. 不直接修改 GitHub Branch Protection

如果当前 Codex 环境有 GitHub 管理权限：

不要未经用户明确要求直接修改 Repository Ruleset。

只在最终报告提出：

```text
main protection still required
```

代码层新增 CODEOWNERS 即可。

---

# 107. Commit Strategy

禁止一个巨大 commit。

建议：

```text
1. refactor(runtime): separate authority hard gate from enforcement mode

2. security(context): remove caller cwd authority and add context assertion

3. contracts: add provenance and intent v3 contracts

4. feat(provenance): add signed provenance store and issuer trust

5. feat(runtime): enforce parameter provenance constraints

6. feat(mcp): add MCP provenance integration

7. refactor(runtimeaction): centralize action descriptors

8. contracts: add effect evidence contract

9. feat(effect): add effect evidence store and observers

10. feat(completion): add minimal task completion evaluation

11. benchmark: add D0-D5 runtime security harness

12. test: add adversarial provenance/effect/recovery coverage

13. docs: ADRs, threat model, capability matrix, README

14. governance: add CODEOWNERS
```

---

# 108. Definition of Done — Authority

### DoD-A1

Mandatory authority invalid：

```text
required + audit
required + warn
required + block
```

全部 effective deny。

### DoD-A2

Optional legacy never-bound session 保持兼容。

### DoD-A3

Previously bound session 不得降级。

### DoD-A4

`context.cwd` 不再扩大 Authority。

### DoD-A5

Trusted workspace 必须来自 signed authority/assertion。

---

# 109. Definition of Done — Provenance

### DoD-P1

存在 signed ProvenanceAssertion Contract。

### DoD-P2

Decision client 不能自报 authoritative provenance。

### DoD-P3

存在 TrustedSourceIssuer registry。

### DoD-P4

Parameter → Provenance refs 可以验证。

### DoD-P5

Provenance 绑定：

```text
task
session
agent
```

### DoD-P6

Intent V3 能定义 parameter provenance constraints。

### DoD-P7

MCP 默认 untrusted。

### DoD-P8

普通 Agent transform 不提高 trust。

### DoD-P9

相同值不同来源能产生不同授权结果。

### DoD-P10

High-impact parameter 无合法 provenance 时 fail closed / hold。

---

# 110. Definition of Done — RuntimeAction

### DoD-R1

存在统一 RuntimeActionDescriptor。

### DoD-R2

Grant/Intent/Taint/Provenance 使用同一个 Tool semantic source。

### DoD-R3

Shell 继续保留 unknown Effect。

### DoD-R4

现有 tool/resource/effect regression 全部通过。

---

# 111. Definition of Done — Effect

### DoD-E1

存在 EffectEvidence Contract。

### DoD-E2

Decision token 不能伪造 external independent evidence。

### DoD-E3

Tool success 不自动成为 verified effect。

### DoD-E4

file.write 存在 host observer fixture。

### DoD-E5

network.request 存在 controlled external oracle fixture。

### DoD-E6

denied action 出现真实 effect 时产生 security finding。

### DoD-E7

conflicting evidence 被明确表示。

### DoD-E8

存在 minimal CompletionStatus。

---

# 112. Definition of Done — Benchmark

### DoD-B1

建立：

```text
benchmarks/runtime-security/
```

### DoD-B2

实现 D0–D5 数据模型。

### DoD-B3

至少 20 个 deterministic security scenarios。

### DoD-B4

每类攻击至少有 benign control。

### DoD-B5

报告：

```text
false allow
false deny
benign completion
unknown effect
D2–D5 outcomes
```

### DoD-B6

没有 Oracle 的样本不得计 D5 success/failure。

---

# 113. Definition of Done — Compatibility

### DoD-C1

Trusted Intent V2 历史 Receipt 仍可验证。

### DoD-C2

Intent V2 dual-read 保留。

### DoD-C3

OpenClaw approval execution recheck 不退化。

### DoD-C4

Binding revocation 不退化。

### DoD-C5

Hermes / OpenClaw / CodeBuddy 现有核心测试通过。

### DoD-C6

Legacy optional authorization 继续按现有安全兼容语义工作。

---

# 114. Definition of Done — Engineering

### DoD-G1

Go race tests 全绿。

### DoD-G2

全仓 CI green。

### DoD-G3

没有新增无界 map。

### DoD-G4

没有新增第二套 signing/canonicalization。

### DoD-G5

没有新增 LLM final authorization。

### DoD-G6

没有把实现 evidence 写成 production supported。

---

# 115. 完成后必须输出 Engineering Report

完成代码后，不要只回复：

```text
Done
```

必须输出以下报告。

---

## A. Actual Baseline

```text
starting SHA
final SHA
branch
```

---

## B. Architecture

说明最终：

```text
Authority
→ Context
→ Provenance
→ RuntimeAction
→ Decision
→ Execution
→ EffectEvidence
```

流程。

---

## C. Trust Boundaries

明确：

```text
Who issues Intent?

Who issues Context Assertion?

Who can report untrusted Provenance?

Who can issue authoritative Provenance?

Who can submit Tool Observation?

Who can submit independent Effect Evidence?
```

---

## D. Changed Files

列关键文件和职责。

---

## E. Security Invariants

逐条说明 INV-1～INV-7 如何实现。

---

## F. Negative Test Table

至少：

| Test                         | Expected     | Actual |
| ---------------------------- | ------------ | ------ |
| required+warn missing Intent | deny         |        |
| forged cwd                   | deny         |        |
| forged USER provenance       | deny         |        |
| MCP recipient injection      | deny         |        |
| same value trusted USER      | allow        |        |
| provenance replay            | deny         |        |
| fake tool success            | not verified |        |
| denied action real effect    | incident     |        |
| conflicting effect           | conflicting  |        |

---

## G. Benchmark

输出：

```text
scenario count

D2 attempt rate

D3 materialization rate

D4 observed effect rate

D5 independently verified effect rate

false allow

false deny

benign task completion

unknown effect
```

---

## H. Performance

实际：

```text
P50
P95
P99
```

分别报告：

```text
authority
provenance
decision
receipt
effect processing
```

不要虚构。

---

## I. Compatibility

报告：

```text
Intent V2
old Receipts
OpenClaw
Hermes
CodeBuddy
optional legacy
```

---

## J. CI

列运行命令和结果。

---

## K. Residual Risks

至少保留：

```text
desktop-same-uid

no malicious-process isolation

explicit provenance only; no full neural semantic causality

unknown transforms remain unknown

MCP provenance does not prove data truth

EffectEvidence coverage is partial

host observer is not equivalent to OS-isolated oracle

no complete SaaS effect verification

no complete Managed Linux

no Multi-Agent Delegation DAG

no universal Behavioral Sandbox

Windows resource semantics remain separately unverified
```

---

# 116. 禁止使用的产品宣称

本轮完成以后仍然不要写：

```text
solves prompt injection

100% secure

all agent effects verified

full information-flow control

complete provenance

production-ready managed isolation

all platforms supported
```

---

# 117. 可以使用的准确表述

本轮完成后，如果证据通过，可以说：

> SIQ Agent Security can deterministically bind selected high-impact runtime parameters to verifiable provenance assertions and distinguish tool-reported outcomes from independently collected effect evidence.

中文：

> SIQ Agent Security 已能够针对选定的高影响运行参数，将其授权与可验证来源证据绑定，并明确区分工具自报结果与独立采集的效果证据。

---

# 118. 本轮完成后的目标架构

```text
                TRUSTED AUTHORITY
                       │
              Signed Intent
                       │
              Context Assertion
                       │
                       ▼
               ┌──────────────┐
               │  AgentShield │
               └──────┬───────┘
                      │
             RuntimeActionDescriptor
                      │
          ┌───────────┼────────────┐
          ▼           ▼            ▼
        Grant       Intent      Provenance
          │           │            │
          └───────────┼────────────┘
                      ▼
                Runtime State
                Taint / Trifecta
                      │
                      ▼
               Authority Gate
                      │
                      ▼
              Policy Evaluation
                      │
                      ▼
          allow / deny / hold / redact
                      │
                      ▼
               Decision Receipt
                      │
                      ▼
              Platform Execution
                      │
             ┌────────┴────────┐
             ▼                 ▼
       Tool Observation    Effect Observer
             │                 │
             └────────┬────────┘
                      ▼
                EffectEvidence
                      │
                      ▼
               CompletionStatus
```

---

# 119. 最终安全模型

当前：

```text
Grant
∩ Intent
∩ RuntimeState
```

本轮完成后目标：

```text
Grant
∩ Intent
∩ TrustedContext
∩ ParameterProvenance
∩ RuntimeState
```

之后：

```text
Decision
→ Execution
→ EffectEvidence
```

即：

```text
Agent 可以提出动作，
但不能自行制造 Authority；
外部内容可以影响数据，
但不能自行制造可信 Provenance；
Tool 可以报告结果，
但不能自行证明真实 Effect。
```

---

# 120. 开始执行

不要只输出：

```text
设计方案
TODO
建议
```

请直接：

```text
inspect latest main
create branch
implement
write schemas
write tests
run race tests
run CI-equivalent validation
update docs
produce benchmark smoke results
produce final Engineering Report
```

如果某一项因为外部平台、OS 权限或第三方能力无法完成：

1. 不要伪造完成；
2. 保留 `unverified`；
3. 提供已完成的代码和 fixture；
4. 给出具体 blocker；
5. 给出下一步真实验收命令；
6. 继续完成其余不受阻塞的工作。

核心原则：

```text
Evidence First.
No security claim without evidence.
No model-generated authority.
No tool-reported success masquerading as verified effect.
```

这一版我建议你**直接整段发给 Codex**。和上一轮相比，最大的变化是：不再继续投入 Trusted Intent V2 本身，而是正式进入 **Provenance-Bound Effect Security**，同时先把 `Authority Hard Gate` 和 `context.cwd` 两个真实授权边界问题收口。完成这轮后，再适合单独做 **Managed Linux + Multi-Agent Delegation + Behavioral Sandbox**。
