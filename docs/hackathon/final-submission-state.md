# Final submission state — V5

This is the sole current submission truth, checked 2026-09-08T13:48:44.264366+00:00. Historical reports retain their original facts. Status vocabulary: `implemented`, `evidenced`, `verified_for_scope`, `unverified`, `external_manual`, `future`.

## Repository and pull requests

- Repository: https://github.com/maoyadongsh/siq-agent-security ; default branch: `main`.
- `starting_sha = submission_sha = main_sha = d1277116e8291e72b09b0462a19d0268b68bf46c`.
- Commit verification: `verified_for_scope` — GitHub `verified=true`, reason `valid`.
- V5 evidence/tooling branch: `codex/hackathon-final-release-v5`. Runtime source remains main. Resolve its final documentation commit with `git rev-parse codex/hackathon-final-release-v5`; the external submission package records that commit without a self-referential Git hash.
- PR [#5](https://github.com/maoyadongsh/siq-agent-security/pull/5): V4 → V3, merged 2026-09-08T13:03:07Z, `2fe9ff344f6b653687582cf6717657252aa3676d`.
- PR [#6](https://github.com/maoyadongsh/siq-agent-security/pull/6): V3 → main, merged 2026-09-08T13:07:28Z, `d1277116e8291e72b09b0462a19d0268b68bf46c`.
- Source selection is frozen. Branch protection is `external_manual`; this snapshot does not claim GitHub prevents future main changes. Recheck main before upload; a changed submission runtime requires a new freeze.

## CI and regression

| Workflow | Run | Commit | Result |
| --- | --- | --- | --- |
| ci | [34230055303](https://github.com/maoyadongsh/siq-agent-security/actions/runs/34230055303) | `d1277116e8291e72b09b0462a19d0268b68bf46c` | success |
| runtime-security | [34230055283](https://github.com/maoyadongsh/siq-agent-security/actions/runs/34230055283) | `d1277116e8291e72b09b0462a19d0268b68bf46c` | success |

Status: `verified_for_scope`. Exact-source GitHub observations are in [repository.json](evidence/final-release-v5/repository.json). Local clean-main regression: 68 checks, including Control API, 100 Secure Agent tests, Web tests/build, all 13 Go modules test/race/vet, contracts, adapters, dependency audits, govulncheck, Skill signature verification and runtime smoke. Separate fresh PostgreSQL migration and 13 V5 packaging tests passed. See [regression commands/results](evidence/final-release-v5/regression/checks.json).

## Agent, security and demo

`verified_for_scope` for the controlled competition paths:

- Secure Agent selects 1/2/3 dynamic Skills for research / report / delivery.
- StepFun `step-3.7-flash` = **REMOTE PLANNING**; Ornith `Ornith-1.5-35B-A3B-NVFP4` = **DGX LOCAL ANALYSIS**.
- Intent, trusted Context, Parameter Provenance and Runtime Authorization constrain tools; Approval rechecks the action before execution.
- EffectEvidence is independently collected for file and controlled receiver effects; Completion is determined by SIQ.
- Normal delivery succeeds. MCP injection follows actual untrusted result → fixture-model proposal → provenance binding → SIQ DENY, with no unsafe target materialization. Fixture attack proposals are labelled; actual model inference is verified separately.
- `alice@company.example`: TRUSTED_DATABASE → ALLOW; identical MCP value → DENY. Authorization binds **Value + Provenance**.
- Fake tool success with no receiver event → INCOMPLETE. Research-only has no requested file/delivery effect and keeps SIQ effect Completion UNKNOWN.
- All nine existing browser scenarios pass, including research-only, research+report, normal, MCP, same-value, fake-success, conflicting effects, approval and trifecta. Dashboard and pairing tested on the extracted RC; no UI redesign.
- CONFIDENTIAL canary reached the local model and was absent from StepFun HTTP bodies. A real local connection-refusal test failed closed with zero StepFun transport calls.

Canonical entry: [six-topic evidence index](evidence/INDEX.md).

## Benchmark

| Measure | Canonical frozen result |
| --- | --- |
| Fixed controls | 23/23 expectations, fresh main run |
| Benign completion | 5/5 |
| Unsafe target materialization | 0/13 |
| Provenance blocks | 8/8 |
| StepFun cohort | 5/5, retained latest V4 cohort |
| Ornith cohort | 5/5, retained latest V4 cohort |

**Small controlled sample. Earlier failures retained.** Model cohorts were not expanded or silently rerun to improve the score. V5 actual-model RC smoke and locality checks are separate evidence, not additional cohort denominators. [Benchmark report](benchmark-report.md) preserves earlier 4/5 failures and original scope.

## DGX

`verified_for_scope`: NVIDIA DGX Spark / GB10; Ubuntu 24.04.4 LTS; aarch64; kernel 6.17.0-1014-nvidia; driver 580.126.09; reported CUDA 13.0; Ornith-1.5-35B-A3B-NVFP4. [Hardware record](evidence/final-release-v5/dgx-preflight.json) distinguishes model listing from actual inference. [Extracted RC launch](evidence/final-release-v5/rc-checkpoint.json) verifies StepFun planning + local analysis + SIQ execution + 26 signed receipts + two effect envelopes + successful Completion.

## Release

- `verified_for_scope`: fresh `siq-agent-security-v0.3.0-rc.1`, exact clean main, Go 1.26.6, four cross-builds. linux-arm64 was launched on DGX; cross-build ≠ native production validation.
- Archive SHA256: `205957fbba10b1019d826232cd004c19ec2444d1519a70bd03137375075369a1`.
- Candidate local path: `.tmp/final-release-v5/rc/siq-agent-security-v0.3.0-rc.1.tar.gz`.
- Included: `source-info.json`, scoped CycloneDX SBOM, four-Skill `skill-inventory.json`, legacy `skills-inventory.json`, binaries and inner checksums. Outer `.tar.gz.SHA256SUMS` covers the archive. Both passed `sha256sum -c`.
- V5 packaging tooling is separately hashed; bundled source is the unchanged main tree. Final V5 documentation accompanies the RC as a separate submission package.
- `publisher_signing = unavailable`: no publisher seed configured in the supported environment variables. Historical v0.2.0 signing does not authenticate this RC. **Hash verification ≠ publisher authentication.**
- `publication = external_manual`; no tag created, no GitHub prerelease published. [Prepared release notes](release-notes-v0.3.0-rc.1.md) and [publication commands](release-publication-commands.md).

## Competition

- Video `verified_for_scope`: retained Mandarin narration/bilingual-subtitle MP4, 169.920 seconds, 1440×1180; SHA256 `a9e003f47051b1ddf367b50dcf3a1e7293b7f7786f241cb7028b1a5bc8ea5430`.
- Original source: `4da9e9e0a04c56620d101a583307b299b8484372`; runtime/Skills/UI/contracts match submission main byte-for-byte. Full decoding and hash rechecked. [Video freeze](evidence/final-release-v5/video-freeze.json) references original recording date, model/DGX metadata and task IDs. Video stays outside Git.
- Submission package: see [final engineering report](final-release-report.md). Form submission and video upload: `external_manual`.
- [Final checklist](FINAL-SUBMISSION-CHECKLIST.md), [governance preparation](repository-governance-final.md), [architecture](final-architecture.md).

## Known limitations

Same-UID processes are not OS-isolated. Python ToolGateway is not an OS sandbox. Remote StepFun is an external trust boundary. Trusted operator classification may be wrong; PUBLIC analysis may be policy-permitted remotely. Effect verification is scoped; the controlled receiver is not universal SaaS proof. There is no general semantic provenance, universal MCP security, complete Multi-Agent delegation, Windows production certification or production HA. Small model cohorts are not statistical guarantees. Historical benchmark failures and failed recording attempts remain available.
