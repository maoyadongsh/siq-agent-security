# SIQ Agent Security

## DGX Spark Agent Skills Hackathon — Final Hardening & Competition Freeze V4

---

# 0. 本轮任务性质

本轮不是新一轮功能扩张。

当前项目已经具有：

```text
Secure Agent
+
secure-research
secure-report
secure-delivery
+
StepFun
+
DGX Spark
+
Trusted Intent V3
+
Trusted Context
+
Parameter Provenance
+
Runtime Authorization
+
Stateful Taint / Lethal Trifecta
+
Human Approval
+
EffectEvidence
+
Completion
+
Competition Dashboard
+
Hackathon Benchmark
```

本轮目标只有四个：

```text
1. 收紧 Model Egress / DGX Locality
2. 让 Agent Skills 从固定 Pipeline 升级为受约束动态编排
3. 完成 Release / CI / Governance Hardening
4. 冻结比赛 Demo / Evidence / Submission Package
```

原则：

> 不再增加与比赛无直接关系的新安全模块。

禁止本轮新增：

```text
Managed Linux full implementation
Multi-Agent Delegation DAG
General Sandbox Engine
Universal SaaS Effect Verification
Neural Taint
General Memory IFC
New Enterprise Authority Plane
New microservice
New Agent framework
```

---

# 1. Repository Baseline

Repository：

```text
maoyadongsh/siq-agent-security
```

已知比赛分支：

```text
codex/dgx-spark-hackathon-v3
```

已知远端 HEAD：

```text
9b4aaeae1a089b54fbbc50c33cdb72616be2b1b1
```

但开始前不得假设这是最新状态。

执行：

```bash
git fetch --all --prune

git checkout codex/dgx-spark-hackathon-v3
git pull --ff-only

git status
git log -10 --oneline
```

记录：

```text
starting_sha
```

如果该分支已经继续前进：

以最新远端 HEAD 为实际起点。

本轮创建：

```text
codex/hackathon-final-hardening-v4
```

从最新比赛分支创建。

禁止直接改 main。

---

# 2. 开发前必须完成 Current-State Audit

先重新审计：

```text
apps/secure-agent/
skills/
apps/agentshield/
apps/web/src/local/
deploy/dgx-spark/
benchmarks/hackathon/
docs/hackathon/
scripts/hackathon/
```

以及：

```text
HACKATHON.md
README.md
final-engineering-report.md
acceptance-matrix.md
limitations.md
submission-checklist.md
```

生成：

```text
docs/hackathon/final-hardening-audit.md
```

分类：

```text
implemented
evidenced
needs-hardening
unverified
future
```

不要根据旧文档自动认为能力仍然有效。

---

# 3. 本轮最高安全原则

继续保持以下不变量。

## INV-1

```text
Agent may propose actions,
but may not manufacture authority.
```

## INV-2

```text
Model output = proposal/data
≠ authority
```

## INV-3

```text
MCP / Web / Tool / Memory
≠ trusted provenance
```

## INV-4

```text
Tool success
≠ verified real-world effect
```

## INV-5

```text
Unknown evidence remains UNKNOWN.
```

## INV-6

```text
Security-sensitive egress
must have an explicit trust boundary.
```

新增本轮核心不变量：

## INV-7 — Model Egress Boundary

> 远程模型调用不得成为绕开 SIQ 数据出网治理的隐式通道。

## INV-8 — Model Planning ≠ Fixed Pipeline

> Agent 可以选择 Skills，但不能绕过确定性依赖、Authority 和 ToolGateway。

---

# 4. WORKSTREAM A — Model Egress & DGX Locality

优先级：

# P0

这是本轮最重要任务。

---

# 5. 当前需要解决的问题

当前架构中：

```text
secure-research
↓
GitHub source content
↓
Source.content
↓
ModelProvider.research()
↓
StepFun HTTPS
```

StepFun HTTP 调用不经过：

```text
ToolGateway
→ SIQ runtime authorization
```

因此存在一个独立的模型出网边界。

这并不等于现有代码有已证明的数据泄漏漏洞，但它使系统形成：

```text
Tool Egress
= SIQ governed

Model Egress
= separate direct path
```

本轮必须明确解决。

---

# 6. A1 — 数据分级

新增明确的数据分类。

建议：

```python
class DataSensitivity:
    PUBLIC
    INTERNAL
    CONFIDENTIAL
    SECRET
```

或者符合现有代码风格的枚举。

至少区分：

```text
public metadata
public source
private source
confidential fixture
secret
```

不要自动把 GitHub public source 当成企业私有源码。

但必须让任务显式带：

```text
source_sensitivity
```

或由可信 operator/config 确定。

模型不得自行降低敏感等级。

---

# 7. A2 — Model Capability Policy

每个 ModelProvider 增加明确属性。

例如：

```python
ModelCapabilities(
    locality="remote" | "local",
    allowed_sensitivity=...,
    can_receive_raw_source=True/False,
)
```

StepFun 当前：

```text
locality = remote
```

Ornith：

```text
locality = local_dgx
```

不得用模型自己返回的信息决定 locality。

---

# 8. A3 — 推荐比赛架构

采用：

```text
USER
 ↓
StepFun
Task Understanding / Planning
 ↓
Secure Agent
 ↓
DGX Local Model
Sensitive Research / Code Analysis
 ↓
Agent Skills
 ↓
SIQ
 ↓
Tools
```

即：

### StepFun

负责：

```text
goal understanding
planning
skill selection
non-sensitive task reasoning
```

### DGX Local Model

负责：

```text
source review
private document analysis
sensitive payload reasoning
```

这样比赛故事变成：

> StepFun 负责智能规划，DGX Spark 负责本地敏感推理，SIQ 负责执行授权。

---

# 9. A4 — 不允许隐式 fallback

模型切换必须：

```text
explicit
observable
auditable
```

禁止：

```text
StepFun failed
→ silently switch Ornith
```

或：

```text
Ornith failed
→ silently send private source to StepFun
```

必须产生：

```text
provider_transition event
```

记录：

```text
from_provider
to_provider
reason
task_id
sensitivity
allowed
```

---

# 10. A5 — Research Routing

修改研究路径：

```text
ModelRouter
```

而不是直接：

```text
self._model.research(...)
```

建议：

```python
model_router.research(
    question,
    sources,
    sensitivity=...
)
```

Routing 规则：

```text
PUBLIC
→ StepFun OR local model

INTERNAL
→ policy configurable

CONFIDENTIAL
→ local DGX only

SECRET
→ local DGX only or reject
```

V1 不需要复杂策略语言。

---

# 11. A6 — StepFun Planning Payload

StepFun planning 阶段不得收到：

```text
raw repository file content
secret
confidential fixture bytes
trusted provenance signatures
SIQ signing material
admin credentials
```

允许：

```text
task goal
repository identifier
selected file paths
Skill catalog
public metadata
```

---

# 12. A7 — Model Egress Evidence

每次远程模型调用记录非敏感元数据：

```text
model_provider
model
operation
task_id
payload_digest
payload_classification
elapsed_ms
status
```

不得记录：

```text
API key
raw confidential prompt
full sensitive payload
```

UI 可显示：

```text
StepFun · Remote Planning
```

或者：

```text
Ornith · DGX Local Analysis
```

让评委肉眼看懂数据流。

---

# 13. A8 — Model Egress Tests

至少：

### ME-01

PUBLIC source → StepFun research allowed if configured.

### ME-02

CONFIDENTIAL source → StepFun raw-content call rejected.

### ME-03

CONFIDENTIAL source → Ornith local allowed.

### ME-04

StepFun timeout → no silent source migration.

### ME-05

Operator explicitly switches provider → audit record exists.

### ME-06

Model cannot change source sensitivity.

### ME-07

Prompt injection in source cannot request remote provider escalation.

### ME-08

Secret/config values never appear in model diagnostics.

---

# 14. WORKSTREAM B — Dynamic Agent Skills Orchestration

优先级：

# P0

当前 Skill 工程已经真实存在。

本轮不要重新开发 Skills。

目标是：

> 从固定三步 workflow 升级为受约束的 Skill composition。

---

# 15. 当前问题

当前 TaskPlan 基本要求：

```text
secure-research
↓
secure-report
↓
secure-delivery
```

三项必须全部出现。

这会让比赛中：

```text
“Agent autonomously selects skills”
```

的说服力不足。

---

# 16. B1 — TaskPlan V2

新增比赛应用内部 TaskPlan V2。

模型可以选择合法子集。

允许：

### Query A

```text
“分析这个 repo”
```

计划：

```text
secure-research
```

### Query B

```text
“分析并保存报告”
```

计划：

```text
secure-research
secure-report
```

### Query C

```text
“分析、生成报告并发给 Alice”
```

计划：

```text
secure-research
secure-report
secure-delivery
```

---

# 17. B2 — Dependency Graph

Skill Registry 明确定义依赖：

```text
secure-research:
    requires = []

secure-report:
    requires = ["secure-research"]

secure-delivery:
    requires = ["secure-report"]
```

模型：

```text
selects skills
```

确定性 validator：

```text
validates dependency graph
```

---

# 18. B3 — Skill Registry Schema

建议 Skill metadata：

```text
name
description
input_schema
output_schema
requires
allowed_tools
security_requirements
```

保持闭集：

```text
trusted built-in registry
```

比赛前不要做任意第三方 Skill 动态执行。

---

# 19. B4 — Model Cannot Invent Skills

模型输出：

```text
secure-upload-to-dropbox
```

如果不存在：

```text
skill_unregistered
```

直接拒绝。

禁止自动映射到：

```text
shell
HTTP
generic tool
```

---

# 20. B5 — Model Cannot Skip Dependencies

如果模型输出：

```text
secure-delivery
```

没有 report：

```text
plan_dependency_invalid
```

不能自动补齐后悄悄继续。

可由 Agent：

```text
return structured planning error
```

并允许模型重新规划一次。

如果做 replan：

必须有：

```text
bounded max retries
```

例如：

```text
max_plan_attempts = 2
```

---

# 21. B6 — Dynamic Skill Demo

比赛增加一个很短的展示：

输入：

> “只分析，不要发出去。”

Dashboard 显示：

```text
Selected Skills

✓ secure-research

– secure-report

– secure-delivery
```

随后输入：

> “生成报告并发给 Alice。”

显示：

```text
✓ secure-research
✓ secure-report
✓ secure-delivery
```

这样评委一眼看到：

> Agent Skills 是真实选择，不是写死 Pipeline。

---

# 22. B7 — Skill Planning Tests

至少：

### SP-01

research only → 1 Skill.

### SP-02

research + report → 2 Skills.

### SP-03

full delivery → 3 Skills.

### SP-04

delivery without report → reject.

### SP-05

unknown skill → reject.

### SP-06

duplicate Skill → reject unless explicit contract permits.

### SP-07

tool name inserted as Skill → reject.

### SP-08

model tries to add approval/signing Skill → reject.

---

# 23. WORKSTREAM C — DGX Spark Competition Visibility

优先级：

# P1

DGX 实机证据已经存在。

本轮不是继续做 benchmark。

而是让评委清楚知道：

> DGX Spark 在真正承担什么计算。

---

# 24. C1 — Dashboard Hardware Card

Demo 页面增加小卡片：

```text
NVIDIA DGX Spark

GPU
GB10

Local Model
Ornith-1.5-35B-A3B-NVFP4

Local Inference
READY

SIQ Runtime
READY
```

数据来自实际 preflight/runtime。

不能硬编码：

```text
GB10 READY
```

如果读取失败：

```text
UNVERIFIED
```

---

# 25. C2 — Model Locality Indicator

每个 Model Action 标注：

```text
REMOTE · StepFun
```

或者：

```text
LOCAL · DGX Spark · Ornith
```

Sensitive research 最好现场明确显示：

```text
LOCAL ANALYSIS
```

---

# 26. C3 — DGX Runtime Metrics

只展示少量真实指标：

```text
current model
inference duration
GPU model
optional GPU utilization
```

不要在比赛 UI 堆：

```text
CUDA kernel statistics
full nvidia-smi
```

---

# 27. C4 — DGX Fail-State

如果 GPU / local model 不可达：

UI 必须：

```text
DGX LOCAL MODEL UNAVAILABLE
```

如果当前任务需要 confidential local inference：

```text
task fails closed
```

不能自动远程发送。

---

# 28. WORKSTREAM D — Release Hardening

优先级：

# P0

比赛前必须完成。

---

# 29. D1 — 当前分支 PR

从：

```text
codex/hackathon-final-hardening-v4
```

向：

```text
codex/dgx-spark-hackathon-v3
```

提交 PR。

不要直接 merge。

PR 必须包含：

```text
Architecture changes
Security invariants
Model egress changes
Skill planning changes
Tests
Benchmark delta
Known limitations
```

---

# 30. D2 — Remote CI

必须让 GitHub Actions 真正运行。

当前本地 CI-equivalent 证据不能替代：

```text
pull_request CI
```

至少要求：

```text
ci
runtime-security
competition tests
web build
secure-agent tests
```

全部 green。

最终报告记录：

```text
workflow run ID
commit SHA
job count
conclusion
```

---

# 31. D3 — Main Protection

当前 main 仍未保护。

Codex 不要在没有明确用户授权的情况下自行修改 repository settings。

但必须生成：

```text
docs/hackathon/repository-governance-actions.md
```

写明建议人工设置：

```text
Require pull request

Require CI checks

Block force push

Require conversation resolution

CODEOWNERS review for security-sensitive paths
```

---

# 32. D4 — Clean Source Build

这是必须解决的。

禁止下一候选包继续从：

```text
dirty worktree
```

构建。

流程：

```text
commit all intended files
↓
remote CI green
↓
merge/freeze exact source commit
↓
git status = clean
↓
clean checkout
↓
build
```

验证：

```bash
git diff --quiet
git diff --cached --quiet
```

---

# 33. D5 — Candidate Identity

候选包必须包含：

```text
source-info.json
```

至少：

```text
git_sha
git_ref
build_time
go_version
python_version
node_version
target
```

不再需要 dirty worktree manifest。

---

# 34. D6 — Release Candidate

目标：

```text
siq-agent-security-v0.3.0-rc.1
```

如果已有 tag 规则冲突：

遵循仓库现有 convention。

不要发布：

```text
v0.3.0 stable
```

---

# 35. D7 — RC Artifacts

至少：

```text
linux-arm64 binary
other existing targets if already supported

SBOM
SHA256SUMS
Skill inventory
Source identity
Hackathon quick start
Evidence summary
```

---

# 36. D8 — Signing

如果仓库已有 release signing / provenance 机制：

复用。

禁止建立第二套签名体系。

如果当前无法正式签名：

明确：

```text
unsigned release candidate
```

不要伪造签名或使用测试密钥冒充 publisher signing。

---

# 37. WORKSTREAM E — Evidence Consolidation

优先级：

# P0

当前证据很丰富，但比赛阅读路径太长。

---

# 38. E1 — Evidence Index

新增：

```text
docs/hackathon/evidence/INDEX.md
```

第一页只允许 5 个主题。

## 1. Agent Skills

证明：

```text
Agent actually selected and executed Skills
```

## 2. NVIDIA DGX Spark

证明：

```text
real hardware
local model
runtime
```

## 3. StepFun

证明：

```text
actual inference
provider identity
```

## 4. Security

证明：

```text
MCP injection
provenance
trifecta
approval
```

## 5. Effect & Completion

证明：

```text
verified
incomplete
conflicting
```

---

# 39. E2 — Evidence Manifest

新增：

```text
docs/hackathon/evidence/evidence-manifest.json
```

结构例如：

```json
{
  "source_sha": "...",
  "dgx": {...},
  "stepfun": {...},
  "skills": {...},
  "security": {...},
  "effect": {...},
  "benchmark": {...}
}
```

每项只引用：

```text
canonical evidence files
```

不要复制数据。

---

# 40. E3 — Raw Evidence

不要删除原始证据。

但 README/HACKATHON 不要直接链接几十个：

```text
dashboard-*
browser-*
regression-*
```

全部通过 INDEX 进入。

---

# 41. E4 — Benchmark Summary

比赛主页面只展示：

```text
23 fixed control tasks

Benign completion
5/5

Unsafe target tool materialization
0/13

Provenance violation blocks
8/8

Latest StepFun sample
5/5

Latest Ornith sample
5/5
```

同时保留：

```text
small sample
earlier failures retained
```

说明。

---

# 42. WORKSTREAM F — Competition UI Freeze

优先级：

# P1

目标：

> 评委 10 秒内理解发生了什么。

---

# 43. F1 — UI 四块保持不变

最终：

```text
CURRENT TASK

AGENT SKILLS

SECURITY DECISIONS

EFFECT / COMPLETION
```

不要继续增加复杂安全后台控件。

---

# 44. F2 — Agent Skills 必须视觉突出

例如：

```text
PLAN

1 ✓ secure-research
2 ✓ secure-report
3 → secure-delivery
```

或者 research-only：

```text
1 ✓ secure-research
```

这是比赛主题最重要的视觉元素之一。

---

# 45. F3 — Security Decision

至少显示：

```text
ALLOW
DENY
HOLD
```

和：

```text
reason_code
```

专业详情可折叠。

---

# 46. F4 — Provenance Visualization

MCP attack：

```text
Recipient
attacker@evil.example

Source
MCP

Trust
UNTRUSTED

Decision
DENY
```

Same-value：

```text
Value
alice@company.example

Trusted Directory → ALLOW

MCP → DENY
```

---

# 47. F5 — Effect Visualization

Fake Success：

```text
TOOL REPORTED
success

EFFECT EVIDENCE
missing

COMPLETION
INCOMPLETE
```

这是最有辨识度的 Demo 之一。

---

# 48. WORKSTREAM G — Demo Freeze

优先级：

# P0

不要比赛当天现场选择十种功能。

冻结主 Demo。

---

# 49. 主 Demo

唯一主故事：

> 分析 GitHub 项目，生成安全报告，发送给 Alice。

流程：

```text
User
↓
StepFun Plan
↓
secure-research
↓
DGX Local Analysis
↓
secure-report
↓
secure-delivery
↓
SIQ
↓
EffectEvidence
↓
Verified Completion
```

---

# 50. Demo Act 1 — 正常任务

目标：

```text
全部成功
```

强调：

```text
Agent autonomously selects Skills
```

---

# 51. Demo Act 2 — MCP Injection

恶意 MCP：

```text
Alice → attacker@evil.example
```

Agent 可以选择它。

SIQ：

```text
DENY
```

强调：

> Model can be fooled. Runtime authority cannot be self-created.

---

# 52. Demo Act 3 — Same Value / Different Provenance

展示：

```text
alice@company.example
```

trusted：

```text
ALLOW
```

MCP：

```text
DENY
```

一句：

> SIQ authorizes not only the value, but where that value came from.

---

# 53. Demo Act 4 — Fake Success

Tool：

```text
success=true
```

Effect：

```text
not observed
```

Completion：

```text
INCOMPLETE
```

一句：

> The tool can report success. It cannot prove the real-world effect.

---

# 54. Demo Act 5 — Human Approval

如果现场时间允许：

```text
HOLD
→ Approve
→ Recheck
→ Execute
```

如果时间有限：

将它作为：

```text
secondary optional demo
```

---

# 55. WORKSTREAM H — Demo Video

优先级：

# P0

当前仓库明确记录：

```text
no recorded video yet
```

比赛前必须完成。

---

# 56. H1 — 录制 2–3 分钟 Demo

结构：

```text
0:00–0:15
Problem

0:15–0:40
Agent Skills + DGX + StepFun

0:40–1:15
Normal task

1:15–1:45
MCP attack

1:45–2:10
Same-value provenance

2:10–2:30
Fake success / EffectEvidence

2:30–2:45
Conclusion
```

---

# 57. H2 — 视频必须真实

禁止：

```text
editing an ALLOW into a DENY

speeding up to hide failures without disclosure

using fixture while labelling StepFun

using Ornith output labelled StepFun
```

可以剪辑等待时间。

但画面需要显示：

```text
provider
task ID
source SHA
```

至少在片头或片尾。

---

# 58. WORKSTREAM I — Regression

优先级：

# P0

本轮修改可能影响：

```text
Model Provider
TaskPlan
Skill dependencies
UI
build
```

必须完整回归。

---

# 59. Secure Agent Tests

全部现有测试必须通过。

新增：

```text
model-egress tests

dynamic-plan tests

DGX-locality tests

provider-switch tests

skill dependency tests
```

---

# 60. AgentShield Tests

禁止因为比赛应用改坏：

```text
Authority Hard Gate

Intent V2/V3

Provenance

EffectEvidence

Completion

Approval

Binding Revocation
```

执行：

```bash
go test ./...
go test -race ./...
go vet ./...
```

---

# 61. Full Repo Checks

执行仓库已有：

```text
Control API tests

Web tests/build

Agent tests

Contract tests

Adapters

Runtime security smoke

Dependency audits

gitleaks

govulncheck
```

---

# 62. Competition E2E

至少重新执行：

```text
normal

research-only

research+report

MCP attack

same-value provenance

fake success

conflicting effect

approval

trifecta
```

---

# 63. StepFun E2E

至少重新跑独立 cohort。

不要删除失败样本。

报告：

```text
attempts
completed
timeouts
format failures
```

---

# 64. DGX Local Model E2E

至少：

```text
public source analysis
confidential-local-only analysis
```

证明：

```text
raw confidential source
does not reach remote provider
```

---

# 65. WORKSTREAM J — Documentation Claims

更新：

```text
README.md
HACKATHON.md
architecture.md
limitations.md
final-engineering-report.md
submission-checklist.md
```

---

# 66. README 关键叙事

建议最终：

# SIQ Agent Security

## Secure Runtime for Agent Skills

> Agent Skills define what agents can do.
> SIQ defines what they are allowed to do.

再增加：

> StepFun plans the task. DGX Spark keeps sensitive analysis local. SIQ authorizes consequential actions.

---

# 67. 禁止新的夸大声明

禁止：

```text
all model traffic is secure
```

除非所有路径都验证。

禁止：

```text
all enterprise code stays local
```

如果 PUBLIC 配置仍允许 StepFun research。

准确说：

> Sensitive workloads can be policy-routed to the DGX-local model; remote planning is kept separate from runtime authority.

---

# 68. 最终比赛安全架构

目标：

```text
                     USER
                       │
                       ▼
                    StepFun
              Task Planning / Routing
                       │
                       ▼
                 Secure Agent
                       │
            ┌──────────┴───────────┐
            │                      │
            ▼                      ▼
     Agent Skill Plan        Model Router
                                   │
                     ┌─────────────┴──────────────┐
                     ▼                            ▼
               Remote StepFun              DGX Local Model
                public/meta               sensitive analysis
                     │                            │
                     └─────────────┬──────────────┘
                                   ▼
                              Agent Skills
                                   │
                                   ▼
                        SIQ Agent Security
                         ├── Intent
                         ├── Context
                         ├── Provenance
                         ├── Runtime State
                         ├── Approval
                         └── Receipt
                                   │
                                   ▼
                                 Tools
                                   │
                                   ▼
                               Execution
                                   │
                                   ▼
                            EffectEvidence
                                   │
                                   ▼
                              Completion
```

---

# 69. 最终比赛公式

Agent intelligence：

```text
StepFun
+
DGX Local Model
+
Agent Skills
```

Security：

```text
Grant
∩
Intent
∩
Trusted Context
∩
Parameter Provenance
∩
Runtime State
```

Verification：

```text
Decision
→ Execution
→ EffectEvidence
→ Completion
```

最终：

# Trusted Agent Execution

---

# 70. DoD — Model Egress

必须全部满足：

* StepFun remote / Ornith local 明确标识；
* raw confidential content 不发送 StepFun；
* remote/local routing 由 trusted policy 决定；
* 模型不能降低敏感等级；
* fallback 不静默；
* provider switch 有审计；
* diagnostics 不泄露 credential；
* UI 能显示 remote/local；
* tests 覆盖上述场景。

---

# 71. DoD — Skills

必须：

* Agent 能选择 1/2/3 Skill 合法组合；
* dependencies deterministic；
* unknown Skill deny；
* skip dependency deny；
* model cannot invent authority Skill；
* all Tools still go through ToolGateway；
* Skill selection 页面可见。

---

# 72. DoD — Release

必须：

* PR 存在；
* remote CI green；
* exact commit recorded；
* clean checkout；
* clean build；
* RC identity exact；
* SHA256；
* SBOM；
* Skill inventory；
* candidate boots；
* main not modified outside approved merge path。

---

# 73. DoD — Evidence

必须：

```text
evidence/INDEX.md
evidence-manifest.json
```

并且评委从 HACKATHON.md 最多两次点击：

即可找到：

```text
Agent evidence
DGX evidence
StepFun evidence
Security evidence
Effect evidence
```

---

# 74. DoD — Demo

必须能重复：

```text
research only

normal delivery

MCP attack

same-value provenance

fake success
```

全部：

```text
one command or dashboard action
```

---

# 75. DoD — Video

至少一份最终比赛 Demo 视频已录制。

记录：

```text
source SHA
model config
DGX config
date
```

视频文件是否入 Git：

按大小与赛事提交要求决定。

不要把大型视频强行提交源码仓库。

---

# 76. 本轮禁止重构

除非解决明确 bug，不要重构：

```text
Intent contracts

Provenance signing

EffectEvidence signing

Receipt chain

Control Plane

Adapters

OpenShell
```

避免引入比赛前安全回归。

---

# 77. Suggested Commit Sequence

建议：

```text
docs: audit final hackathon hardening scope

feat(agent): add model locality and sensitivity routing

test(agent): cover model egress boundaries

feat(agent): support constrained dynamic skill plans

test(agent): validate skill dependency graph

feat(web): expose skill plan and model locality

docs(dgx): align local inference competition story

docs(evidence): add canonical hackathon evidence index

test(hackathon): rerun final end-to-end scenarios

chore(release): prepare clean v0.3.0-rc.1 candidate

docs(hackathon): freeze submission and final engineering report
```

---

# 78. Final Engineering Report V4

新增：

```text
docs/hackathon/final-hardening-report.md
```

必须包括：

## A

```text
starting_sha
final_sha
branch
```

## B

Model routing：

```text
StepFun
Ornith
sensitivity policy
```

## C

Agent Skills：

```text
selected Skills
dependency validation
```

## D

Security：

```text
Intent
Context
Provenance
Runtime
Effect
Completion
```

## E

DGX：

```text
hardware
local model
actual tests
```

## F

Remote CI：

```text
run IDs
jobs
status
```

## G

RC：

```text
tag/candidate
hash
SBOM
source identity
```

## H

Demo：

```text
normal
dynamic skill
MCP
same-value
fake-success
approval
```

## I

Performance：

仅更新本轮实际重新测量数据。

## J

Residual Risks。

---

# 79. Residual Risks 必须保留

最终仍明确：

```text
same-UID processes are not OS-isolated

built-in Python ToolGateway is not an OS sandbox

remote StepFun is an external trust boundary

public-source remote analysis may be policy-permitted

no general semantic provenance

no universal SaaS effect verification

no universal MCP security

no full multi-agent delegation

no Windows production certification

no production HA

small model cohorts are not statistical guarantees
```

---

# 80. 最终比赛产品声明

如果本轮全部验收完成，可以使用：

> **SIQ Agent Security is a secure runtime for Agent Skills. StepFun performs task planning, NVIDIA DGX Spark can keep sensitive AI analysis local, and SIQ independently authorizes consequential actions using signed intent, trusted context and parameter provenance. Execution results are separated from independently collected effect evidence before a task is treated as complete.**

中文：

> **SIQ Agent Security 是面向 Agent Skills 的可信执行运行时。StepFun 负责任务理解与规划，NVIDIA DGX Spark 承担本地敏感 AI 推理，SIQ 在模型之外基于签名意图、可信上下文和参数来源独立授权真实动作，并将工具报告与效果证据分离后再判断任务是否真正完成。**

---

# 81. Codex 最终执行要求

不要只写计划。

完成：

```text
inspect
→ implement
→ test
→ run
→ benchmark
→ verify
→ open PR
→ remote CI
→ clean build
→ prepare RC
→ document
```

如果某项依赖外部权限：

例如：

```text
repository branch protection

official signing key

official release publication

competition video upload
```

且当前没有权限：

不要阻塞其余工作。

必须：

1. 完成所有可执行工程；
2. 标记 external/manual action；
3. 给出准确操作步骤；
4. 不把未执行动作写成完成。

---

# 82. 最终优先顺序

严格：

```text
P0-1 Model Egress / Locality
         ↓
P0-2 Dynamic Skill Planning
         ↓
P0-3 Regression
         ↓
P0-4 PR + Remote CI
         ↓
P0-5 Clean RC
         ↓
P0-6 Evidence Index
         ↓
P0-7 Demo Freeze / Video
```

完成上述以后：

# STOP FEATURE DEVELOPMENT.

比赛前不再增加新安全模块。

目标从此变为：

```text
稳定
清楚
真实
可重复
有证据
```

---

# 83. 最终判断标准

本轮完成以后，一个评委必须能够在 5 分钟内明确回答：

### 1

Agent 是否真的使用 Agent Skills？

```text
YES — dynamically selected from a trusted registry.
```

### 2

StepFun 是否真的使用？

```text
YES — task planning / routing.
```

### 3

DGX Spark 是否真的使用？

```text
YES — local model and runtime on actual DGX hardware.
```

### 4

SIQ 有什么不同？

```text
The model proposes.
SIQ authorizes.
```

### 5

Prompt Injection 成功骗过模型怎么办？

```text
It still cannot manufacture authority.
```

### 6

Tool 说成功怎么办？

```text
Tool success is reported evidence,
not proof of the real effect.
```

### 7

如何证明项目不是 PPT？

```text
Exact commit
+
Remote CI
+
DGX evidence
+
Signed receipts
+
Effect evidence
+
Repeatable demo
+
Clean RC
```

最终比赛核心：

> **Skills 给 Agent 能力。
> SIQ 给能力边界。
> DGX Spark 让敏感智能留在本地。
> Evidence 证明任务真的完成。**
