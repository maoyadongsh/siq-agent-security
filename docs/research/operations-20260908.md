# Research open-source operations — 2026-09-08

Implementation branch: `codex/research-open-source-r1`, based on V5 documentation commit `e72e8b36a71ae7f7f1fecd587bbe6eb2353f24d2`. This is the research-cycle operations record; V5 competition source, artifacts, video and denominators remain frozen.

## Implemented

- Owner confirmed ownership of project code/original research materials. Apache-2.0, scoped CC BY 4.0, NOTICE, attribution inventory and software citation are on disk. Seventy Mermaid component license/notice sets and Web runtime/font licenses are retained.
- GitHub private vulnerability reporting, secret scanning, push protection, dependency alerts/security updates and Discussions enabled with API readbacks. Main protected by PR/code-owner review, resolved conversations, current checks and no force-push/deletion. Single-maintainer administrator bypass is disclosed in GOVERNANCE.md.
- Contribution/DCO, security/response, governance/conduct files, six issue forms and a PR template added. Reproduction, dataset/export, evaluation, claims/evidence, citation and artifact-identity documents created.
- Historical seed reviewed separately from a clean heuristic scan. Owner confirmed local-only use, current local key differs, no external revocation identified. History retained with explicit warning; no secret values exported.
- Local CPU fixture tests: nine browser cases passed. Full fixed controls: 23/23 expectations; 318 receipt signatures and 20 effect envelopes verified. These are dirty development-worktree checks, not a new clean-release acceptance. No new paid model inference.
- Hosted-Linux research CI passed all nine browser scenarios without model keys or GPU (run 34241801688, source 3e3112e). Only public summaries are uploaded. The source prerelease packager also passed three negative tests and a clean-source archive build; final main will be packaged separately.

## Remote integration and remaining work

PR [#7](https://github.com/maoyadongsh/siq-agent-security/pull/7) carries this implementation. Five scoped contribution issues [#8–#12](https://github.com/maoyadongsh/siq-agent-security/issues?q=is%3Aissue+is%3Aopen) were created; Discussions and research topics are enabled. No outside researcher has been contacted or represented as a reproducer. Final remote commit, PR and CI results are recorded in evidence/remote-integration.json once available. The initial API operation records are [platform security](evidence/platform-security-readback.json), [main protection](evidence/branch-protection-readback.json) and [private reporting](evidence/private-reporting-readback.json).

First release scope is an unsigned source-only research prerelease; see release-scope.md. A new binary research release still requires actual-payload SBOM/notice verification, a clean finalized source build and separate release acceptance. The old unsigned V5 RC is not silently republished as a licensed research binary. No publisher key or archival account is configured. No DOI, Zenodo upload, independent external reproduction, research-community response, new confirmatory experiment or paper submission is claimed.

These remaining release/research milestones are tracked explicitly in the [71-task ledger](../open-source-research-tasks-20260908.md); repository setup does not complete the multi-month research programme.
