# Final release engineering report — V5

Authorized engineering and submission preparation are frozen. This branch changes documentation and release tooling only; it does not change runtime security, Skills, UI, contracts or benchmark corpus. [Current truth](final-submission-state.md) is the sole status authority.

## A. Source identity

- starting_sha: `d1277116e8291e72b09b0462a19d0268b68bf46c`.
- submission_sha: `d1277116e8291e72b09b0462a19d0268b68bf46c`.
- main_sha: `d1277116e8291e72b09b0462a19d0268b68bf46c` (remote rechecked before handoff).
- final_branch_sha: resolved by `git rev-parse codex/hackathon-final-release-v5`; the exact value is written into the external `submission-package.json` after committing these documents, avoiding a self-referential commit hash.
- branch: `codex/hackathon-final-release-v5`.
- prepared tag: `siq-agent-security-v0.3.0-rc.1`; no tag created.
- Clean source: `.tmp/final-release-v5/source`, detached main; empty porcelain status before and after packaging and regression.
- `source-info.json` independently records the V5 builder SHA256. `--source-root` allows reviewed release tooling to package exact main without altering main's runtime source. Candidate sources retain main's historical documentation; V5 submission documents accompany the RC separately.

## B. Merge history

V4 → V3: PR #5, merged 2026-09-08T13:03:07Z, `2fe9ff344f6b653687582cf6717657252aa3676d`.
V3 → main: PR #6, merged 2026-09-08T13:07:28Z, `d1277116e8291e72b09b0462a19d0268b68bf46c`.
[Read-only repository observations](evidence/final-release-v5/repository.json) preserve GitHub commit verification and PR state. No V5 merge was performed.

## C. CI and regression

Main `ci` run [34230055303](https://github.com/maoyadongsh/siq-agent-security/actions/runs/34230055303): success, 28 jobs.
Main `runtime-security` run [34230055283](https://github.com/maoyadongsh/siq-agent-security/actions/runs/34230055283): success; toolchain/contracts jobs pass, nightly-only jobs are excluded on push. [Job contexts](evidence/final-release-v5/runtime-security-jobs.json).
Historical exact-source V4 PR runs remain in [remote-ci.json](evidence/final-hardening-v4/remote-ci.json); they are not relabelled as main runs.

68 clean-main local checks passed, with exact commands, cwd, duration and exit code in [checks.json](evidence/final-release-v5/regression/checks.json). They include all 13 Go modules `go test ./...`, `go test -race ./...`, `go vet ./...`; Control API pytest; 100 Secure Agent tests; contracts; adapter tests; Web tests/build; npm/pip dependency audits; Go 1.26.6 govulncheck; runtime-security smoke plus independent evidence verification; existing Skill manifest verification. Fresh PostgreSQL migration to `0016` passed. Separately, 13 V5 package/evidence tests and Ruff passed; all four Skills self-admitted with conditions under the native RC. Candidate secret scan passed calibrated gitleaks. Source/submission scan and package hash verification are recorded with the final bundle.

## D–E. Agent and security

Actual StepFun `step-3.7-flash` remote planning, Ornith `Ornith-1.5-35B-A3B-NVFP4` local analysis, and Dynamic Skills are preserved. Python ToolGateway mediates the existing allowed tools; it is not an OS sandbox.

Intent ∩ Context ∩ Provenance ∩ RuntimeState constrains Grant. Approval requires recheck. SIQ receipts bind actions; independent scoped effect observations decide Completion. MCP injection and same-value MCP origin are denied before delivery executor entry. Fake success with absent receiver evidence remains INCOMPLETE. No new security architecture or feature was needed.

## F. DGX and locality

NVIDIA DGX Spark, GB10, Ubuntu 24.04.4 LTS, aarch64, driver 580.126.09, reported CUDA 13.0. [Hardware record](evidence/final-release-v5/dgx-preflight.json) is separate from actual inference.

[PUBLIC/CONFIDENTIAL actual-model tests](evidence/final-release-v5/locality.json) both pass: local transport receives the synthetic canary; remote StepFun requests contain no canary. [Real loopback connection-refusal fault](evidence/final-release-v5/local-failure.json) fails closed with zero remote calls. Tests did not stop the shared local model or alter live services.

## G. Benchmark

Fresh fixed controls: 23/23 expectations, benign completion 5/5, unsafe materialization 0/13, provenance blocks 8/8. Independent verification: 318 receipts, 20 effect envelopes. Latest retained StepFun and Ornith cohorts each remain 5/5; earlier 4/5 failures retained. Small controlled sample, no cohort expansion or statistical guarantee. [Canonical report](benchmark-report.md) preserves every earlier denominator and failure.

## H. Release

Candidate: `siq-agent-security-v0.3.0-rc.1`, exact main source. Four targets: linux-arm64, linux-amd64, darwin-arm64, windows-amd64.exe. Only linux-arm64 has native DGX service validation in this freeze; cross-build ≠ native production validation.

Archive: `.tmp/final-release-v5/rc/siq-agent-security-v0.3.0-rc.1.tar.gz`.
SHA256: `205957fbba10b1019d826232cd004c19ec2444d1519a70bd03137375075369a1`.

Source identity, scoped CycloneDX SBOM, Skill descriptor/version/source digests, tools and dependencies, binaries and inner checksums are included. Archive checksum is external to avoid self-reference. Both checksum lists passed `sha256sum -c`. Historical plural Skill inventory remains for old launcher compatibility; the singular V5 inventory covers all four Skills.

`publisher_signing = unavailable`, `publication = external_manual`. Supported publisher-key environment variables are not configured; no temporary key was substituted. Hash verification ≠ publisher authentication. The historical v0.2.0 manifest authenticates only its own release. [Prepared prerelease notes](release-notes-v0.3.0-rc.1.md) and [commands](release-publication-commands.md).

Submission package location: `.tmp/final-release-v5/submission/`. It contains the RC archive, outer checksum, retained final MP4, an archive of committed V5 submission documents, and `submission-package.json` binding runtime SHA, final documentation branch SHA and file hashes. Package checksums are verified after assembling the committed documents. No video is added to Git.

## I. Demo and video

[Extracted candidate launch](evidence/final-release-v5/rc-checkpoint.json): health ready; actual StepFun → Ornith → SIQ → file/delivery effects → verified Completion; 26 receipts and two effect envelopes verified. Package unchanged after execution.

[Browser smoke](evidence/final-release-v5/browser/result.json): nine existing scenarios pass, including pairing, 1/2/3 Skill selection, normal, MCP, same-value, fake-success and approval. No page errors, no token in localStorage, HttpOnly cookie, mobile no horizontal overflow. Negative model proposals are explicitly fixture-labelled and use real SIQ decisions. The required user approval is performed by the test operator in controlled fixtures.

Existing narrated video retained: SHA256 `a9e003f47051b1ddf367b50dcf3a1e7293b7f7786f241cb7028b1a5bc8ea5430`, 169.920 seconds, 1440×1180. Original recording: 2026-09-08T12:43:11.469517Z, runtime source `4da9e9e0a04c56620d101a583307b299b8484372`. Runtime/UI/Skills/contracts are byte-identical to submission main. Full decoding and hash verification passed. [Original task IDs and model settings](evidence/final-hardening-v4/video.json); [narration metadata](evidence/final-hardening-v4/narrated-video-zh.json). No rerecord trigger occurred.

## J. Manual remaining tasks

- Competition form submission and video upload: external_manual; no external receipt available.
- Official publisher signing: unavailable until a real publisher key is supplied through the existing mechanism.
- GitHub prerelease: external_manual; artifact/notes/tag command prepared, no publication authorization supplied.
- Branch protection: external_manual; admin capability exists but no explicit settings instruction. [Exact preparation](repository-governance-final.md).

## K. Residual risks

Same-UID processes are not OS-isolated. Python ToolGateway is not an OS sandbox. Remote StepFun is an external trust boundary. Trusted operator classification may be wrong. PUBLIC analysis may be policy-permitted remotely. Effect verification is scoped. Controlled receiver is not universal SaaS proof. No general semantic provenance, universal MCP security, complete Multi-Agent delegation, Windows production certification or production HA. Small model cohorts are not statistical guarantees.

Only P0 correctness/security defects or a broken competition submission reopen code changes. Feature/refactor/architecture proposals go to [POST-HACKATHON.md](POST-HACKATHON.md).
