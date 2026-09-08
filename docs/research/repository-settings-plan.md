# Repository governance implementation

Authorization: repository owner requested direct open-source operations on 2026-09-08. Baseline: [API snapshot](evidence/baseline.json).

Apply to main: pull requests, dismiss stale reviews, CODEOWNERS review, one approving review, conversation resolution, all 28 observed ci job contexts and the two required runtime-security jobs; checks must be current. Disable force pushes and deletion. Administrators retain GitHub administrator bypass (`enforce_admins=false`): there is currently only one maintainer and no independent reviewer. This exception is explicit; do not describe current governance as independent review. Normal contributions use PRs; owner exceptions need a recorded reason and successful checks. No collaborators are added.

Enable private vulnerability reporting, Discussions, secret scanning and push protection, Dependabot alerts and security updates. Keep existing visibility, merge modes and Pages. Secret validity checking is not requested because it can contact providers.

Capture API readbacks after every operation. Rollback: restore the baseline fields via PATCH; main initially had no protection, so DELETE its protection endpoint restores the observed baseline. Do not roll back safety settings merely because historical findings appear. Current scans may identify earlier exposures; enabling a scanner does not revoke credentials.

Required contexts are resolved from successful run 34230055303 job names, not workflow titles. Additional contexts: runtime-security-toolchain and runtime-security-contracts (PR jobs in runtime-security.yml). Scheduled nightly jobs are not required PR checks.

API references: https://docs.github.com/en/rest/branches/branch-protection#update-branch-protection and https://docs.github.com/en/rest/repos/repos#update-a-repository.
