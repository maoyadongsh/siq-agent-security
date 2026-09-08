> Historical snapshot.
> For the current submission state, see: [docs/hackathon/final-submission-state.md](final-submission-state.md).

Current V4 acceptance: [63-task requirement mapping](final-hardening-tasks-v4.md)
and [final engineering report](final-hardening-report.md).

> Historical V3 record. Current V4 development and acceptance are tracked in
> [V4 progress](final-hardening-progress-v4.md), [task ledger](final-hardening-tasks-v4.md)
> and [canonical evidence](evidence/INDEX.md). V4 requires a clean CI-verified
> candidate and a real 2–3 minute recording; V3 dirty-source/video exemptions do not apply.

# V3 requirement audit

Scope: the user-supplied [master plan](master-plan-v3.md), local development,
measured DGX operation and unpublished candidate preparation. The latest provider
instruction is StepFun primary and ornith explicit backup. Historical tests and
current evidence are not silently relabelled. See the final engineering report
for the final candidate identity and acceptance outcome.

| Master-plan sections | Disposition | Evidence and practical scope |
| --- | --- | --- |
| 0–4, 7–8, 55–56 | Implemented and exercised | [Audit](current-state.md), actual SecureApplication/SkillRunner/ToolGateway; reuse existing SIQ APIs and kernel |
| 5–6, 9–10, 58–59 | Measured DGX and model integration | [StepFun](step-plan.md), [ornith](structured-model-output.md), [DGX](dgx-performance-report.md); model proposes, never owns authority |
| 11–14, 16, 57 | Three actual typed Skills | `skills/secure-{research,report,delivery}` and application tests; fixed selected-source research/report/delivery task |
| 15 | Optional, not required | Explain-security-decision Skill not added; existing UI displays SIQ reason/evidence |
| 17–23 | All six required demonstrations | Normal, MCP injection, same-value provenance, [trifecta](lethal-trifecta-demo.md), approval and fake success; additional conflicting-effect scenario |
| 24–28, 60–61 | Real controlled services and SIQ integration | Authenticated directory/MCP/web/receiver, actual files and scoped effect observers; [architecture](architecture.md) |
| 29–33, 62 | Existing local SPA extended | Seven [browser scenarios](evidence/browser-trifecta-final-20260908/result.json); task/Skills/Intent/actions/provenance/effects; reported success stays distinct from verified Completion |
| 34–37 | Linux/DGX profile and evidence | Preflight/start/health/env template, actual GB10/driver/CUDA/RAM/architecture/model and source/Skill hashes; remote weights digest explicitly unverified |
| 38–41, 64 | Security and utility benchmark | [23 full Agent controls and separate real-model cohorts](benchmark-report.md); counts, populations, failure samples, false-deny and missing-effect denominators retained |
| 42–44, 63 | Reproducible automation | Managed start/health/scenarios/stop/reset; pairing renewal; isolate and archive only owned state |
| 45–46, 65 | Submission documents | README/HACKATHON, architecture diagram, demo script, benchmarks, DGX/StepFun evidence, limitations and checklist; video is not a required §65 deliverable and has not been recorded |
| 47–48 | Local RC preparation | [Candidate contract](rc-preparation.md); four binaries, source SHA plus dirty hashes, scoped SBOM, checksums, Skill inventory and quick start; no official signature or release publication claimed |
| 49 | Recommendation recorded | [Readback](evidence/final-regression-20260908/repository-governance.json): main unprotected, account admin access present; no settings write performed |
| 50–54 | Scope and execution order respected | No new memory/security engine, universal provenance, OS sandbox or general delegation implementation; optional work not counted as mandatory completion |
| 66 | Existing Provenance API showcase | Trusted directory allow; MCP deny, including equal recipient text; issuer revocation and scope mismatch controls |
| 67 | Three effect outcomes | Actual receiver match → verified; tool success without receiver → incomplete; substituted receiver bytes → conflicting |
| 68 | Scoped performance measurements | Planning/model transport, SIQ, provenance, effect processing and complete-task percentiles with sample counts and limitations |
| 69–70 | Existing and competition regression | [Local CI-equivalent checks](repository-regression.md), Go matrix, native adapter harnesses, contracts, approved-process revocation, forged provenance and no-effect controls; gateway boundary is not an OS sandbox |
| 71–75, 77 | Narrative and claim boundaries | Actual Agent task/Skill/security/effect chain; no universal security, model-quality or independent-host attestation claims |
| 76 | Final report | Final engineering report records baseline/current source, Agent, DGX, security, Demo, metrics, local checks, package and outstanding external boundaries |

Native macOS/Windows runtime certification, official publisher signing, remote
required CI and repository protection changes are not inferred from local builds.
The original 23-case corpus includes source-taint cases, not a general memory
subsystem; the exact required private-read/web/egress chain is separately captured
with actual StepFun and signed same-session receipts.
