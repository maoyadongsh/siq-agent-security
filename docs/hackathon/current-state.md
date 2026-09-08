# COMP-00 Repository audit and current implementation

Audit date: 2026-09-08. `git fetch --all --prune`, `git checkout main`, and
`git pull --ff-only` completed with a clean worktree before development.

- starting_sha: `e309655915562a27cb98df851c1e46e922563d47`
- branch: `codex/dgx-spark-hackathon-v3`
- Acceptance authority: [user-provided V3 plan](master-plan-v3.md).

| Classification | Current evidence and consequence |
| --- | --- |
| implemented | `apps/agentshield/internal/{receipt,intent,provenance,trustedcontext,runtimeaction,effectevidence,completion}` own authorization and evidence. Reuse their HTTP APIs; no second engine. |
| evidenced | Existing `benchmarks/runtime-security/` runs real SIQ component fixtures, file observers and receiving HTTP servers. Historical evidence lives in `docs/evidence/provenance-v1/`; it does not establish Secure Agent application completion. |
| implemented | Admission, Grant challenge/approve/deploy, Intent V3 and bindings; decision/admin/observer credentials are separated by the server. |
| implemented | Provenance Report/Select APIs mint low-trust MCP assertions; trusted issuers are admin-only. `TRUSTED_DATABASE` is the existing directory source type; `TRUSTED_DIRECTORY` is not in the contract. |
| implemented | Completion requires precommitted digests for `file.write` and `network.request`. A `message.send` receipt alone cannot establish delivery. Use an additionally authorized HTTP sink request and real network observation; label its verification scope. |
| implemented / locally evidenced | Secure Agent CLI/service, three actual Skills, strict ornith/StepFun providers, gateway, task state, isolated authority bootstrap and file/network observers. Step Plan is now primary: an actual task completed with three model calls, 26 verified receipts and two effect readbacks. Ornith remains explicit backup. |
| implemented / browser evidenced | Existing `apps/web/src/local/` now includes `/demo`, four task/Intent/action/effect regions, private pairing and operator approval. Seven scenarios, including the full stateful trifecta chain, and mobile layout checked in a real browser. |
| implemented / locally evidenced | Controlled services, isolated state, DGX profile, automation, approval and 23 Agent controls pass. Latest StepFun and ornith utility cohorts each complete 5/5; earlier failures remain archived. Broader model reliability is not claimed. |
| evidenced / scoped | Actual DGX Spark / GB10, StepFun/ornith inference and all service probes are archived. A live GitHub task completed with three ornith calls, 22 receipts and two effect readbacks. Native non-Linux deployment remains unverified. |
| evidenced / release preparation | Candidate 2 includes four binaries, scoped SBOM/checksums/Skills and passed actual extracted StepFun launch. It is unsigned and unpublished. GitHub readback shows main protection disabled and account admin access present; no settings changed. |
| future | Managed Linux isolation, universal semantic provenance, universal SaaS verification and general delegation DAG remain out of scope. |

## API integration map

| Responsibility | Existing API |
| --- | --- |
| Skill admission and approved policy | `/v1/admit`, `/v1/grants` and Grant lifecycle routes |
| Task authority | `/v1/intents`, `/v1/intent-bindings` |
| Trusted workspace | `/v1/context-assertions` (bound to exact tool call and parameters) |
| Trusted directory | `/v1/provenance-issuers`, `/v1/provenance-assertions` |
| Untrusted MCP | `/v1/provenance-reports`, `/v1/provenance-select` |
| Action / reported outcome | `/v1/decide`, `/v1/observe` |
| Human approval / execution recheck | `/v1/hold/{receipt_id}`, `/v1/hold-status` |
| Independent evidence | `/v1/effect-observers`, `/v1/file-observations`, `/v1/network-observations` |
| Completion | `/v1/tasks/{task_id}/completion` |

## Validation baseline and planned gates

`.github/workflows/ci.yml` covers secret scans/static contracts, Control API
lint/tests/migrations, Edge and every Connector module, both Go toolchains,
web build, OpenClaw adapter regression, AgentShield tests and cross compilation,
and Skill manifest verification/self-admission. Runtime-security workflows add
provenance/effect contracts, benchmark and toolchain security checks.

No historical green result is claimed as a test of this branch. New application
checks must cover provider authority injection, gateway fail-closed behavior,
immutable action parameters, provenance scope and same-value origin differences,
real file/sink effects, fake success, and approval recheck. Full existing checks
will be recorded with exact commands and results before final acceptance.

Current checkpoint: **79 application tests passed**, including eighteen actual
application E2Es, eight HTTP service tests and five lower-level daemon cases. Five repeatable
normal/adversarial/fault scenarios are archived with signed receipt chains and
SIQ-validated effect readbacks in [application evidence](evidence/agent-e2e-20260908.json).
See [progress](progress.md) for completed checks and remaining acceptance work.
The [submission checklist](submission-checklist.md) now links the architecture,
five-minute demo script and explicit limitations. Native Hermes/OpenClaw/CodeBuddy
harnesses and a hashed source-snapshot secret scan are recorded in the
[repository regression report](repository-regression.md). RC packaging and final
engineering acceptance are recorded in the [final engineering report](final-engineering-report.md).
The separate [approval checkpoint](approval-integration.md) covers six controls
and the real operator UI. One actual ornith approval task failed format validation
at planning; it remains recorded as a utility failure, not security success.
A subsequent [real ornith approval run](model-diagnostics.md) completed in 32.3
seconds with three model calls, a real fixed process and verified report/delivery.
Failure diagnostics now retain each attempt without logging raw model content.
The [full Agent benchmark](benchmark-report.md) separately archives 23 controls
and five real ornith tasks, initial failures, current metrics and cryptographic
verification outputs. Security and utility denominators are explicit.
The [provenance UI and renewed pairing](demo-evidence-contract.md) and
[DGX performance distributions](dgx-performance-report.md) are now evidenced.
The latest [live-source checkpoint](live-source-validation.md) completed in 21.90 seconds.
[Structured generation](structured-model-output.md) documents schema-only and direct-output
cohorts separately. The demo now defaults to Step Plan / step-3.7-flash; direct-output ornith is explicit backup.
[Private provider configuration and StepFun evidence](step-plan.md) supersede the earlier deferral.
[Repository regression](repository-regression.md) records local checks, including
649 Control API tests, 79 Agent tests, Go modules, audits and isolated migration replay.
