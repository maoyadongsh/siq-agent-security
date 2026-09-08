# Provenance-bound authorization and effect evidence: implementation report

Status: engineering research report, not peer reviewed. Runtime snapshot and each evidence identity are specified in [claims-evidence.json](claims-evidence.json). This document describes existing behavior rather than asserting priority or accepted novelty.

## System and threat boundaries

The Secure Agent selects research, report and delivery Skills and obtains model proposals. Its Python ToolGateway sends consequential operations through the Go SIQ runtime. Effective authority comes from runtime readback, not model output. Registered intent/context and parameter provenance are bound to the action; held approvals are rechecked before execution. Signed receipts link decisions and outcomes. Independent file/controlled-receiver observers provide action-bound effect evidence, and SIQ derives completion from requirements and those observations.

Relevant source surfaces are `apps/secure-agent/secure_agent`, `apps/agentshield`, `packages/contracts` and `benchmarks/hackathon`. Execution does not establish OS isolation from another same-user process. Trusted source registration and sensitivity classification are operator assumptions. A signed receipt proves a scoped recorded statement under its key; it does not make every observer or input source independently trustworthy.

## Evaluation and observations

The [retrospective protocol](evaluation-protocol.md) describes the existing fixed corpus. [Reproduction instructions](result-reproduction.md) use the same verifier and metrics code as CI. The full development control run has 23 attempted cases and 23 expected outcomes, with 318 receipt signatures and 20 effect envelopes verified. Benign task completion is 5/5; unsafe materialization is 0/13 registered unsafe-target cases. These different populations must not be combined. The report retains failed/blocked, missing and conflicting outcomes instead of counting every tool response as success.

Nine UI fixture cases separately test pairing and visible task/effect behavior. Historical real-model benign utility cohorts report 5/5 in their latest retained runs, with earlier 4/5 failures preserved in the original benchmark report. Fixture attack proposals do not measure model susceptibility, and no model cohort was rerun in this cycle. V5 locality checks observed a confidential canary only in local analysis and tested a local connection refusal with zero remote transport calls; those observations apply to the stated source/model/environment only.

Every numeric claim above links through [claims and evidence](claims-evidence.md) to public records, protocol scope and denominators. The new local runs were produced during development with a dirty-worktree flag. They must not be substituted for a clean released-source acceptance or an external reproduction.

## Limitations and next experiments

The fixed tasks are authored alongside the implementation, publicly visible and small. No confidence interval or universal security rate is claimed. Repeated seeds on one task do not add independent task units. Observer reliability, source-registration errors, unfamiliar input origins, external effect systems and cost/utility tradeoffs need separate experiments. Future work should preregister task units, pilot/held-out split, exclusions, paired analysis and compute budget before confirmatory runs; fixture-only ablations must not weaken released authorization paths.
