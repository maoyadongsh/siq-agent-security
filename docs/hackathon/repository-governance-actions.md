> Historical snapshot.
> For the current submission state, see: [docs/hackathon/final-submission-state.md](final-submission-state.md).

# Repository governance actions · V4

Read-only check on 2026-09-08: repository `maoyadongsh/siq-agent-security`,
default branch `main`, viewer role `ADMIN`, `main.protected=false`. Account
capability is not permission to change settings. No repository setting has been
changed by this work. V4 PRs target `codex/dgx-spark-hackathon-v3`; do not merge
directly or develop on main.

An authorized repository maintainer can configure the following in GitHub:

1. Open repository **Settings → Rules → Rulesets**, create a branch ruleset
   targeting `main`, and choose Active enforcement after reviewing bypass actors.
2. Enable **Require a pull request before merging**, with the team's review count.
3. Enable **Require status checks to pass**, selecting actual checks from the
   successful V4 PR: the ci Control API/Edge/Web/AgentShield/security checks and
   runtime-security toolchain/contracts jobs. Confirm competition tests and
   Secure Agent tests ran inside the contracts job. Do not type invented job names.
4. Block force pushes; require conversation resolution before merging.
5. Add a reviewed `.github/CODEOWNERS` mapping for `packages/contracts/`,
   `apps/agentshield/`, `apps/secure-agent/`, `adapters/runtime/` and workflows to
   actual trusted reviewer accounts/teams, then require code-owner review. Do not
   substitute a nonexistent team. Submit CODEOWNERS through the normal PR path.
6. Re-read branch/ruleset protection and inspect a test PR's checks/review gates.
   Save the rule IDs, date and redacted readback in the evidence manifest.

Read-only verification commands:

```bash
env -u GITHUB_TOKEN gh api repos/maoyadongsh/siq-agent-security/branches/main --jq '{name,protected}'
env -u GITHUB_TOKEN gh api repos/maoyadongsh/siq-agent-security/rulesets
env -u GITHUB_TOKEN gh pr checks PR_NUMBER
```

Other external/manual items remain separate:

- **Official signing:** after publisher authorization, use the existing SIQ
  release-manifest / manifest-verify mechanism with the established publisher
  identity in its protected signing environment. Verify the resulting manifest
  against the trusted publisher key and exact candidate binary hashes. If that
  identity is unavailable, retain `unsigned release candidate`; no test seed or
  historical v0.2.0 signature signs a V4 binary.
- **Official RC publication:** after explicit publication authorization, verify
  the frozen source SHA, successful PR workflow runs, candidate archive hash,
  SBOM and inventory. Follow the existing tag convention without overwriting a
  tag; upload the reviewed RC artifacts and checksums as a prerelease. Do not
  publish v0.3.0 stable or merge the PR as a side effect.
- **Competition video upload:** after the destination, format/size requirements
  and submission credentials are available, upload the recorded final video;
  record its URL, hash, date and source/model/DGX configuration. Keep large video
  files outside source Git. Recorded is distinct from submitted.

These actions do not block independent coding, tests, evidence preparation or an
unsigned local clean RC. Unexecuted actions remain pending in the V4 task ledger.
