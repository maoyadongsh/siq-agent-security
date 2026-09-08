# Repository governance — final preparation

Status: `external_manual`. Read-only GitHub audit found admin capability, `main.protected=false`, and no rulesets. The task supplies conditional authorization, not an instruction to enable settings now. No repository setting was changed.

Repository: https://github.com/maoyadongsh/siq-agent-security

After explicit governance authorization, use Settings → Rules → Rulesets → New branch ruleset (or classic Branch protection rules), target `main`, enable enforcement, and configure:

1. Require a pull request before merging; require review for CODEOWNERS paths using the existing `.github/CODEOWNERS`.
2. Require status checks and require the branch to be up to date. Select the actual **job contexts**, not merely the workflow display names `ci` and `runtime-security`.
3. For `ci`, require all successful job names recorded in [ci-jobs.json](evidence/final-release-v5/ci-jobs.json), including both Go version matrix variants.
4. For `runtime-security`, require `runtime-security-toolchain` and `runtime-security-contracts`. Scheduled-only nightly matrix jobs are excluded from PR-required checks.
5. Block force pushes; block deletion; require conversation resolution. Keep bypass grants minimal and explicitly reviewed.
6. Verify with `gh api repos/maoyadongsh/siq-agent-security/branches/main` and `gh api repos/maoyadongsh/siq-agent-security/rulesets`; archive the readback before marking any setting `verified_for_scope`.

A successful historical workflow does not prove settings enforcement. `.github/CODEOWNERS` remains in place; no rules were relaxed. See [current state](final-submission-state.md).
