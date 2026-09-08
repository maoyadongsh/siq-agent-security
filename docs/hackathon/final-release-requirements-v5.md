# SIQ Agent Security

## DGX Spark Agent Skills Hackathon

## Final Release, Governance & Submission Freeze V5

---

# 0. 本轮任务性质

本轮是：

# FINAL RELEASE & SUBMISSION FREEZE

不是新功能开发。

当前项目已经完成比赛所需核心链路：

```text
User
↓
StepFun Planning
↓
Dynamic Agent Skills
↓
DGX Spark Local Analysis
↓
SIQ Runtime Authorization
↓
Tool Execution
↓
EffectEvidence
↓
Completion
```

已有能力不得重新设计或重复实现：

```text
Admission
Grant
Trusted Intent V2/V3
Authority Hard Gate
Trusted Context
Parameter Provenance
RuntimeAction
Stateful Taint
Lethal Trifecta
Human Approval
Execution Recheck
Receipt Chain
EffectEvidence
Completion
Secure Agent
Dynamic Skills
StepFun
DGX Local Model Routing
Hackathon Dashboard
Benchmark
Demo Fixtures
```

本轮只有五个目标：

```text
1. 最终仓库事实一致性
2. 基于最新 main 生成 clean RC
3. 发布 / 治理收口
4. 最终比赛证据与材料冻结
5. 全面停止功能开发
```

---

# 1. 当前已知基线

Repository：

```text
maoyadongsh/siq-agent-security
```

已知当前 main：

```text
d1277116e8291e72b09b0462a19d0268b68bf46c
```

已知状态：

```text
V4 merged into main
PR #5 merged
PR #6 merged
main CI green
runtime-security green
main commit verified
```

但 Codex 开始前不得假设以上仍为最新。

必须执行：

```bash
git fetch --all --prune
git checkout main
git pull --ff-only

git status
git log -10 --oneline
```

记录：

```text
starting_sha
```

若 main 已继续更新：

以实际最新 SHA 为准。

---

# 2. 创建最终收口分支

从最新 main 创建：

```text
codex/hackathon-final-release-v5
```

禁止直接在 main 上开发。

本轮只允许：

```text
documentation fixes
release tooling
evidence manifests
submission metadata
governance configuration preparation
P0 bug fixes
```

---

# 3. STOP FEATURE DEVELOPMENT

以下内容本轮明确禁止：

```text
Managed Linux
Multi-Agent Delegation
new sandbox
new provenance architecture
new EffectEvidence architecture
new Skill framework
additional Agent framework
new Control Plane
new database
new microservice
new general MCP proxy
new neural taint
new Windows security semantics
new SaaS integrations
```

除非发现会导致当前比赛主链：

```text
错误授权
越权执行
敏感数据错误外发
错误 Completion
Demo 崩溃
```

的真实 P0 Bug。

否则：

# DO NOT MODIFY RUNTIME SECURITY ARCHITECTURE.

---

# 4. TASK-01 — Final Repository Truth Audit

优先级：

# P0

重新审计：

```text
README.md
HACKATHON.md

docs/hackathon/
docs/hackathon/evidence/

apps/secure-agent/
apps/agentshield/
apps/web/src/local/

skills/

benchmarks/hackathon/
benchmarks/runtime-security/

deploy/dgx-spark/

scripts/hackathon/

.github/workflows/
CODEOWNERS
```

检查所有：

```text
branch names
SHA
PR states
CI states
video state
RC state
release state
DGX status
StepFun status
```

是否与当前 GitHub 实际状态一致。

---

# 5. 重点修复历史文档状态漂移

当前历史文档中可能仍保留：

```text
PR #5 remains unmerged

main was not changed

no video recorded

candidate dirty

V4 branch only
```

等历史事实。

不要删除历史证据。

正确方式：

在每份历史文档顶部增加：

```text
Historical snapshot.
For the current submission state, see:
docs/hackathon/final-submission-state.md
```

保留历史内容原样。

---

# 6. TASK-02 — 建立唯一 Current Truth

新增：

```text
docs/hackathon/final-submission-state.md
```

这是比赛提交阶段唯一权威状态文档。

至少包含：

## Repository

```text
repository
default branch
submission SHA
commit verification
```

## Pull Requests

```text
PR #5
PR #6
merged_at
merge SHA
```

## CI

```text
ci workflow
runtime-security workflow
run IDs
conclusion
```

## Agent

```text
Secure Agent
dynamic Skills
StepFun
DGX Local Model
```

## Security

```text
Intent
Context
Provenance
Runtime Authorization
EffectEvidence
Completion
```

## Demo

```text
normal
MCP injection
same-value provenance
fake success
approval optional
```

## Benchmark

仅列当前 canonical 数字。

## DGX

列实际：

```text
hardware
OS
GPU
driver
CUDA
model
```

## Release

```text
release candidate
publication status
signing status
```

## Competition

```text
video
submission package
upload status
```

## Known Limitations

保留所有真实边界。

---

# 7. 状态词必须标准化

全仓库比赛材料统一使用：

```text
implemented
evidenced
verified_for_scope
unverified
external_manual
future
```

禁止：

```text
fully verified
production secure
complete protection
100% secure
```

---

# 8. TASK-03 — Final Evidence Manifest

新增或更新：

```text
docs/hackathon/evidence/evidence-manifest.json
```

必须绑定：

```text
submission_sha
```

结构建议：

```json
{
  "submission_sha": "...",
  "repository": {},
  "ci": {},
  "agent_skills": {},
  "stepfun": {},
  "dgx_spark": {},
  "security": {},
  "effect_evidence": {},
  "benchmark": {},
  "demo_video": {},
  "release": {}
}
```

---

# 9. Evidence Manifest 原则

只引用 canonical evidence。

不要复制原始证据内容。

例如：

```text
benchmark
→ benchmark-report.md

DGX
→ dgx-performance-report.md

V4
→ final-hardening-report.md

video
→ narrated-video evidence

CI
→ workflow run JSON
```

---

# 10. TASK-04 — Evidence Index 最终收口

最终：

```text
docs/hackathon/evidence/INDEX.md
```

评委只需要看到五个入口：

```text
1. Agent Skills
2. NVIDIA DGX Spark
3. StepFun
4. Runtime Security
5. Effect & Completion
```

再增加：

```text
6. Reproducibility / Release
```

---

# 11. 首页不得堆几十份证据

`HACKATHON.md`：

不要直接链接大量：

```text
browser-*
dashboard-*
regression-*
checkpoint-*
```

全部通过：

```text
evidence/INDEX.md
```

进入。

---

# 12. TASK-05 — Submission Source Freeze

决定唯一提交代码 SHA：

```text
SUBMISSION_SHA
```

默认应为：

```text
当前最新 main
```

除非本轮 P0 修复产生新 merge。

最终必须满足：

```text
submission source
=
main HEAD
```

---

# 13. TASK-06 — Fresh Clean Release Candidate

不要直接发布历史本地 RC。

从最终：

```text
SUBMISSION_SHA
```

重新：

```bash
git clone / clean worktree
git checkout --detach $SUBMISSION_SHA
git status --porcelain
```

必须为空。

---

# 14. Clean Source Guard

构建前：

```bash
test -z "$(git status --porcelain)"
```

构建后再次确认源码目录未被构建脚本污染。

不得使用：

```text
dirty-source manifest
```

作为最终候选。

---

# 15. TASK-07 — Build Final RC

目标版本：

```text
siq-agent-security-v0.3.0-rc.1
```

如果 tag 已存在：

不得覆盖。

改为：

```text
v0.3.0-rc.2
```

---

# 16. RC 至少包含

```text
linux-arm64
linux-amd64
darwin-arm64
windows-amd64.exe
```

如果仓库当前仍支持四目标。

但必须注明：

```text
cross-build
≠
native production validation
```

---

# 17. DGX Spark 主目标

比赛核心目标：

```text
linux-arm64
```

必须在真实 DGX Spark：

```text
extract
launch
healthcheck
run demo smoke
```

至少完成一条真实：

```text
StepFun planning
+
DGX local analysis
+
SIQ execution
+
EffectEvidence
+
Completion
```

---

# 18. TASK-08 — RC Metadata

候选必须包含：

```text
source-info.json
```

至少：

```json
{
  "repository": "...",
  "git_sha": "...",
  "git_ref": "...",
  "build_timestamp": "...",
  "go_version": "...",
  "python_version": "...",
  "node_version": "...",
  "targets": []
}
```

---

# 19. TASK-09 — SBOM

生成：

```text
sbom.cdx.json
```

优先 CycloneDX。

必须覆盖：

```text
AgentShield
Secure Agent dependencies
Web production dependencies
```

如果只能覆盖候选包的确定范围：

明确：

```text
scoped SBOM
```

不要称为整个供应链完整 SBOM。

---

# 20. TASK-10 — Checksums

生成：

```text
SHA256SUMS
```

覆盖：

```text
all binaries
archive
SBOM
Skill inventory
source-info
```

重新验证：

```text
sha256sum -c
```

---

# 21. TASK-11 — Skill Inventory

生成：

```text
skill-inventory.json
```

至少：

```text
siq-agent-security
secure-research
secure-report
secure-delivery
```

记录：

```text
version
manifest digest
source digest
tools
dependencies
```

---

# 22. TASK-12 — Release Signing

检查仓库已有 publisher signing 机制。

如果存在真实 publisher key：

复用现有机制。

禁止：

```text
test key
development key
temporary key
```

冒充正式 publisher signing。

---

# 23. 如果没有正式 signing key

最终报告：

```text
publisher_signing = unavailable
```

并明确：

```text
hash verification ≠ publisher authentication
```

不要阻塞 RC 准备。

---

# 24. TASK-13 — Remote CI on Final Submission SHA

最终提交 SHA 必须有真实 GitHub CI。

要求至少：

```text
ci
runtime-security
```

成功。

记录：

```text
workflow
run_id
commit_sha
status
conclusion
```

---

# 25. 必须执行完整回归

至少：

```bash
go test ./...
go test -race ./...
go vet ./...
```

并运行仓库现有：

```text
Control API tests
Web tests
Web build
Secure Agent tests
contract tests
adapter tests
runtime benchmark smoke
dependency audit
govulncheck
gitleaks
migration tests
Skill verification
```

---

# 26. TASK-14 — Competition E2E Freeze

最终至少重新执行：

```text
research only
research + report
normal delivery
MCP recipient attack
same value / different provenance
fake success
approval
```

---

# 27. 正常任务

必须证明：

```text
Agent utility
```

而不是只证明安全拒绝。

至少：

```text
normal task completion
=
PASS
```

---

# 28. MCP Attack

必须保留真实路径：

```text
MCP untrusted result
↓
Agent/model proposal
↓
Parameter provenance
↓
SIQ
↓
DENY
```

禁止：

```text
attack keyword → demo layer deny
```

---

# 29. Same Value / Different Provenance

必须真实展示：

```text
alice@company.example
```

来源：

```text
TRUSTED_DATABASE
→ ALLOW
```

来源：

```text
MCP
→ DENY
```

强调：

```text
Value + Provenance
```

---

# 30. Fake Success

必须：

```text
tool says success
```

但：

```text
independent receiver = no effect
```

则：

```text
Completion = INCOMPLETE / UNKNOWN
```

绝不能显示：

```text
SUCCESS
```

---

# 31. TASK-15 — Model Locality Final Verification

保留：

```text
StepFun
=
REMOTE PLANNING
```

```text
Ornith
=
DGX LOCAL ANALYSIS
```

---

# 32. CONFIDENTIAL Test

最终必须重新验证：

```text
CONFIDENTIAL source
↓
DGX local model
```

并确认：

```text
raw confidential source
not present in StepFun transport
```

使用 canary / digest 证据。

---

# 33. Local Failure

测试：

```text
CONFIDENTIAL
+
DGX local unavailable
```

必须：

```text
FAIL CLOSED
```

不能：

```text
fallback to StepFun
```

---

# 34. TASK-16 — Dashboard Freeze

从此禁止大 UI 改版。

只允许：

```text
bug fix
wording fix
status accuracy fix
```

最终四块：

```text
CURRENT TASK
AGENT SKILLS
SECURITY DECISIONS
EFFECT / COMPLETION
```

---

# 35. Dashboard 必须显示

```text
StepFun · REMOTE
Ornith · DGX LOCAL
```

以及：

```text
selected Skills
actual action
provenance
SIQ decision
effect state
completion state
```

---

# 36. TASK-17 — Video Freeze

已有最终录像的情况下：

禁止因为轻微 UI 改动重新反复录制。

只有以下情况重新录：

```text
submission SHA runtime changed
security semantics changed
visible incorrect claim fixed
video corrupt
critical demo failure
```

---

# 37. 视频元数据

最终记录：

```text
video SHA256
duration
resolution
source SHA
model configuration
DGX configuration
task IDs
recording date
```

---

# 38. 视频不得进入 Git 大对象

若赛事接受上传：

视频保留在正式提交位置。

仓库只保存：

```text
hash
metadata
script
subtitle
```

除非现有 repo 策略明确允许媒体文件。

---

# 39. TASK-18 — README / HACKATHON 最终整理

README 第一屏必须让非安全评委 20 秒理解项目。

建议：

# SIQ Agent Security

## Secure Runtime for Agent Skills

> Agent Skills define what agents can do.
> SIQ defines what they are allowed to do.

再加：

> StepFun plans the task. NVIDIA DGX Spark keeps sensitive analysis local. SIQ independently authorizes consequential actions and verifies their effects.

---

# 40. README 第一层不要讲太多

第一页只讲：

```text
Problem
Architecture
Demo
DGX Spark
StepFun
Agent Skills
Evidence
Quick Start
```

研究历史放后面。

---

# 41. TASK-19 — Competition Submission Checklist

新增唯一：

```text
docs/hackathon/FINAL-SUBMISSION-CHECKLIST.md
```

不要与历史 submission checklist 混淆。

---

# 42. Checklist 至少包含

```text
[ ] GitHub main frozen
[ ] submission SHA recorded
[ ] commit verified
[ ] CI green
[ ] runtime-security green
[ ] DGX verified
[ ] StepFun verified
[ ] Agent Skills E2E verified
[ ] security demo verified
[ ] EffectEvidence verified
[ ] benchmark archived
[ ] video final
[ ] GitHub URL correct
[ ] demo instructions correct
[ ] release candidate correct
[ ] competition form submitted
[ ] video uploaded
```

---

# 43. TASK-20 — Branch Protection

当前 main 未保护。

建议开启：

```text
Require pull request
Require status checks
Require ci
Require runtime-security
Block force push
Require conversation resolution
```

已有：

```text
CODEOWNERS
```

继续使用。

---

# 44. Repository Settings 写操作规则

如果本任务执行环境明确具备 GitHub Admin 权限，并且用户已经授权执行治理设置：

可以实施。

否则：

生成：

```text
docs/hackathon/repository-governance-final.md
```

列出准确设置步骤。

状态：

```text
external_manual
```

不得写：

```text
completed
```

---

# 45. TASK-21 — GitHub Prerelease

最终建议发布：

```text
siq-agent-security-v0.3.0-rc.1
```

类型：

```text
PRE-RELEASE
```

不是 stable。

---

# 46. Prerelease Release Notes

必须明确：

```text
Hackathon candidate

Secure Agent

Dynamic Agent Skills

StepFun task planning

DGX Spark local analysis

Trusted Intent

Parameter Provenance

EffectEvidence

Completion
```

---

# 47. Release Notes 同时必须声明

```text
research / competition candidate

not production certification

same-UID limitation

controlled effect fixtures

limited platform validation

remote StepFun external boundary
```

---

# 48. 发布权限规则

如果没有明确 publisher authorization：

Codex：

```text
prepare release artifacts
prepare release notes
prepare tag command
```

但不要实际发布。

将：

```text
publication = external_manual
```

---

# 49. TASK-22 — Final Architecture Snapshot

新增：

```text
docs/hackathon/final-architecture.md
```

只保留比赛最终架构：

```text
USER
 │
 ▼
StepFun
Task Planning
 │
 ▼
Secure Agent
 │
 ▼
Dynamic Agent Skills
 │
 ├───────────────┐
 │               │
 ▼               ▼
DGX Local AI   SIQ Runtime
 │               │
 │        Intent / Context
 │        Provenance
 │        Runtime Policy
 │        Approval
 │        Receipts
 │               │
 └───────┬───────┘
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

# 50. 最终核心安全公式

保留：

```text
Effective Authorization
=
Grant
∩ Intent
∩ TrustedContext
∩ ParameterProvenance
∩ RuntimeState
```

执行后：

```text
Decision
→ Execution
→ EffectEvidence
→ Completion
```

---

# 51. TASK-23 — Final Benchmark Summary

不要继续扩大 benchmark。

冻结当前 controlled benchmark。

主页面只报告：

```text
Fixed controls
Benign completion
Unsafe materialization
Provenance blocks
StepFun cohort
Ornith cohort
```

并明确：

```text
small controlled sample
```

---

# 52. 不允许重新包装历史失败

已有：

```text
4/5
```

等失败样本继续保留。

最新：

```text
5/5
```

可以报告。

但必须同时：

```text
Earlier failures retained.
```

---

# 53. TASK-24 — Final Security Claims Audit

搜索整个仓库：

```text
100%
fully secure
production ready
solves prompt injection
all effects verified
all MCP
full provenance
all platforms
```

逐一检查。

---

# 54. 可使用的比赛声明

推荐：

> SIQ Agent Security provides an external runtime authority layer for Agent Skills. Models propose plans and actions; SIQ independently validates consequential execution against signed intent, trusted context, parameter provenance and runtime state.

以及：

> StepFun handles task planning, while NVIDIA DGX Spark can keep sensitive AI analysis local.

以及：

> Tool-reported success is separated from independently collected effect evidence before completion is established.

---

# 55. 不可使用

禁止：

```text
Prompt injection solved
```

禁止：

```text
Agent cannot be hacked
```

禁止：

```text
all effects verified
```

禁止：

```text
complete IFC
```

禁止：

```text
production isolation
```

---

# 56. TASK-25 — Final Engineering Report

生成：

```text
docs/hackathon/final-release-report.md
```

---

# 57. Report A — Source Identity

```text
starting_sha
final_branch_sha
submission_sha
main_sha
tag
```

---

# 58. Report B — Merge History

记录：

```text
V4 → V3
V3 → main
```

对应 PR。

---

# 59. Report C — CI

```text
PR runs
main runs
run IDs
results
```

---

# 60. Report D — Agent

```text
StepFun
Ornith
Dynamic Skills
ToolGateway
```

---

# 61. Report E — Security

```text
Intent
Context
Provenance
Runtime
Approval
Effect
Completion
```

---

# 62. Report F — DGX

```text
machine
GPU
driver
CUDA
local model
actual inference
```

---

# 63. Report G — Benchmark

仅真实结果。

---

# 64. Report H — Release

```text
candidate
hash
SBOM
signature state
publication state
```

---

# 65. Report I — Demo

```text
video
scenarios
task IDs
source identity
```

---

# 66. Report J — Manual Remaining Tasks

例如：

```text
competition form upload

video upload

official signing

branch protection
```

如尚未执行。

---

# 67. Report K — Residual Risks

必须至少保留：

```text
same-UID processes are not OS-isolated

Python ToolGateway is not an OS sandbox

remote StepFun is an external trust boundary

trusted operator classification may be wrong

PUBLIC analysis may be policy-permitted remotely

effect verification is scoped

controlled receiver is not universal SaaS proof

no general semantic provenance

no universal MCP security

no complete Multi-Agent delegation

no Windows production certification

no production HA

small model cohorts are not statistical guarantees
```

---

# 68. TASK-26 — Final Smoke Test

最终候选包在 DGX Spark：

```text
extract
↓
start
↓
health
↓
pair
↓
research
↓
report
↓
delivery
↓
effect
↓
completion
```

必须成功。

---

# 69. Adversarial Smoke

至少：

```text
MCP attack
```

确认：

```text
unsafe target materialization = false
```

---

# 70. Fake Success Smoke

确认：

```text
reported success
≠
verified completion
```

---

# 71. TASK-27 — Final Freeze

全部完成后：

创建：

```text
docs/hackathon/FREEZE.md
```

内容：

```text
Submission SHA
RC
CI
DGX
StepFun
Video
Evidence Manifest
Date
```

---

# 72. FREEZE 后规则

只有：

```text
P0 correctness bug
P0 security bug
broken competition submission
```

可以重新开启代码修改。

其他：

```text
feature request
refactor
performance idea
new paper
new architecture
```

全部进入：

```text
POST-HACKATHON.md
```

---

# 73. Post-Hackathon Roadmap

比赛后再继续：

```text
Managed Linux isolation
Enterprise authority distribution
General sandbox orchestration
Multi-Agent delegation
Resource budgets
Windows semantics
Broader EffectEvidence
Advanced provenance
```

本轮不开发。

---

# 74. 建议 Commit 顺序

```text
docs: reconcile final post-merge submission state

docs: establish canonical evidence manifest

chore: prepare clean submission-source release candidate

test: run final competition and security regression

docs: freeze final hackathon architecture and claims

chore: prepare v0.3.0-rc.1 prerelease artifacts

docs: add final submission checklist

docs: record final release engineering evidence

docs: freeze competition source and artifacts
```

---

# 75. Definition of Done — Repository

必须：

```text
main contains final competition implementation
submission SHA known
CI green
runtime-security green
historical docs marked as snapshots
current truth unique
```

---

# 76. DoD — Release

必须：

```text
clean source
fresh build
exact source identity
SBOM
SHA256
Skill inventory
DGX launch
```

---

# 77. DoD — Competition

必须：

```text
Agent Skills visible
StepFun visible
DGX visible
normal task works
attack blocked
effect evidence visible
completion correct
video final
```

---

# 78. DoD — Governance

至少：

```text
branch protection completed
```

或者准确标记：

```text
external_manual
```

不能模糊。

---

# 79. DoD — Evidence

评委从：

```text
HACKATHON.md
```

最多两次点击可以找到：

```text
Agent Skills evidence
DGX evidence
StepFun evidence
security evidence
EffectEvidence
CI
release identity
```

---

# 80. Codex 最终输出格式

完成后仅给一份最终报告。

标题：

# SIQ Agent Security — Final Competition Release Report

包含：

```text
1. Starting SHA

2. Final SHA

3. Submission SHA

4. Branch / PR

5. CI

6. Release Candidate

7. DGX Verification

8. StepFun Verification

9. Agent Skills E2E

10. Security E2E

11. EffectEvidence / Completion

12. Benchmark

13. Video

14. Repository Governance

15. Manual Remaining Actions

16. Residual Risks
```

---

# 81. Codex 不得做的事

不得：

```text
因为“还能优化”继续增加功能
```

不得：

```text
重构核心 security runtime
```

不得：

```text
创建第二套 provenance/effect engine
```

不得：

```text
删除历史失败证据
```

不得：

```text
把 fixture 说成真实第三方效果
```

不得：

```text
把 cross-build 说成 native validation
```

不得：

```text
把 hash 说成 publisher authentication
```

不得：

```text
把 tool success 说成 verified effect
```

---

# 82. 本轮最终原则

# Evidence First.

代码是什么：

由：

```text
SHA
```

证明。

是否通过：

由：

```text
CI
```

证明。

是否运行在 DGX：

由：

```text
hardware/runtime evidence
```

证明。

是否使用 StepFun：

由：

```text
provider evidence
```

证明。

是否阻断攻击：

由：

```text
real SIQ decision
+
tool materialization
```

证明。

是否真正完成：

由：

```text
EffectEvidence
+
Completion
```

证明。

---

# 83. 最终停止条件

当以下全部成立：

```text
main frozen
CI green
clean RC ready
DGX verified
StepFun verified
Agent Skills verified
security scenarios verified
EffectEvidence verified
video final
evidence indexed
submission package ready
```

执行：

# STOP DEVELOPMENT.

之后只进行：

```text
PPT
演讲稿
现场 Demo 彩排
评委 Q&A
正式提交
```

项目比赛版不再增加功能。
