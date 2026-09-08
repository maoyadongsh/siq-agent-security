> Historical snapshot.
> For the current submission state, see: [docs/hackathon/final-submission-state.md](final-submission-state.md).

# Local repository acceptance — 2026-09-08

This is local DGX aarch64 validation of the dirty competition branch, not a
remote GitHub Actions result or an RC approval. The baseline remains
`e309655915562a27cb98df851c1e46e922563d47`; no commit or release was created.

[62 command results](evidence/final-regression-20260908/checks.json) record exact
commands, working directories, exit codes and elapsed times. Every command
passed. Logs are adjacent to that manifest. Coverage includes:

- Twelve existing CI static/checkpoint/performance-harness checks.
- Control API/application/benchmark lint, scenario schemas and both benchmark
  unit suites, Hermes adapter tests and OpenClaw adapter regressions.
- AgentShield, Edge Agent and all eleven Connector modules: build, vet and race
  tests under Go 1.26.6. The historical signed Skill manifest also verifies;
  this does not assert that new binaries match old release pins.
- Web build and eleven tests; production npm audit found zero vulnerabilities.
- Locked Python dependency audit found no known vulnerabilities in audited
  dependencies. The unpublished local application package cannot be checked
  against PyPI; it remains explicitly excluded from that database audit.

[Additional checks](evidence/final-regression-20260908/additional-checks.json)
record 648 passing Control API tests with an isolated temporary SQLite database,
69 passing Secure Agent tests and 17 passing final-provider tests. The eight
new proposal-schema cases also pass. A new temporary PostgreSQL 17 instance
replayed Alembic to `0016 (head)` and was removed afterward; no existing database
was used. `govulncheck v1.7.0` under Go 1.26.6 found no vulnerabilities in the
AgentShield module at scan time.
The minimum supported Go 1.22.12 toolchain also passes `go test ./...` for
AgentShield; its separate log is `agentshield-go122-tests.log`. That compatibility
run is not a claim that the older standard library is vulnerability-free.

Existing runtime smoke evidence verifies ten receipts/eight effect envelopes.
Recovery evidence verifies two pending records, two recovery records, one
observer revocation, one receipt and one verified file completion. The existing
Hermes MCP bridge harness also passes; its own limitations explicitly exclude
native platform execution and independent effect evidence.

## Installed runtime follow-up

Three existing native harnesses now pass against installed runtimes, with
temporary configuration/state and the current daemon:

| Runtime | Evidence | Verified receipt count | Actual scope |
| --- | --- | --- | --- |
| Hermes | [Native harness](evidence/final-regression-20260908/native-hermes.json) | 412 | Installed plugin loader and tool dispatcher; real SIQ HTTP and signed chain |
| OpenClaw | [Native harness](evidence/final-regression-20260908/native-openclaw.json) | 412 | Installed plugin loader, native before wrapper and Pi tools; harness invokes after relay |
| CodeBuddy 2.146.0 | [Native CLI](evidence/final-regression-20260908/native-codebuddy.json) | 13 | Eight native CLI invocations using temporary installer/configuration and deterministic loopback model |

These are actual native-runtime integration checks, but synthetic operators and
calls. They do not establish a human approval journey, GUI/channel integration,
OS isolation, or universal platform support. No user's runtime configuration was
modified. The full native conversation/approval and four-platform Skill package
acceptance requirements remain distinct from these successful harnesses.

The earlier Gitleaks snapshot returned zero findings, but subsequent inspection
found that `.gitleaks.toml` did not enable default rules. That
[old manifest](evidence/final-regression-20260908/source-secret-scan.json) is
**invalid acceptance evidence**, despite recording an actual zero exit code.
Default rules are now enabled. Exact synthetic test-value exceptions require
matching test paths; public source-hash metadata exceptions match strict JSON
file-path/64-hex records. One adjacent-literal test rewrite preserves its runtime
value while preventing a scanner from spanning two header-only fixtures as a
private-key block. All 90 threat-analysis tests pass.

`scripts/check_gitleaks_config.py` verifies real scanner detection on ordinary
paths, permitted test paths and hash-evidence paths, checks private-key block
detection and path-restricted exceptions, and rejects the former empty-rule
configuration. CI now runs this calibration before its existing Gitleaks action.
Public scan summaries include no raw credentials. The eventual RC package and
Git history remain separate scan scopes.
The subsequent [calibrated source scan](evidence/final-regression-20260908/source-secret-scan-accepted.json)
has zero findings and records its exact source/configuration hashes. Earlier
intermediate scans with findings remain archived and do not count as passing.

These results do not replace native-platform acceptance, four-platform Skill
installation checks, secret scanning, candidate packaging or remote required CI.
The complete two-toolchain connector matrix is recorded below. The latest
direct-output model cohort and live GitHub checkpoint have separate evidence
and are not counted as these deterministic tests.

## History classification and minimum-toolchain follow-up

The [minimum-toolchain matrix](evidence/final-regression-20260908/minimum-go-matrix.json)
passes all 36 build/vet/race commands for Edge and eleven Connectors under
Go 1.22.12, completing the local two-toolchain module matrix.

The [Git-history scan](evidence/final-regression-20260908/git-history-secret-scan.json)
processed 294 local commits and returned one historical GitHub-token-pattern
finding in `edge/agent/evidence_test.go`. Subsequent inspection identified an
explicit synthetic decimal-cycle fixture. An exact-value and exact-path exception
was added, with scanner calibration proving other tokens in that same file and
the same synthetic value outside that file remain detected. The
[triaged history scan](evidence/final-regression-20260908/git-history-secret-scan-triaged.json)
processed all 294 commits with zero findings. No credential was used or history
rewritten; the original failed scan remains archived.

## Final stateful-demo follow-up

[Exact commands and logs](evidence/final-regression-20260908/final-followup-checks.json)
record 649 Control API tests, 79 Agent tests, ten package/proof tests, eleven Web
tests, local/control Web builds, AgentShield Go 1.26.6 vet/race and Go 1.22.12
tests. The 79 Agent tests include eighteen actual application E2Es and compare
the displayed state with the corresponding SIQ signed receipt. The final browser
run covers seven scenarios; StepFun trifecta separately verifies eleven receipts.

[GitHub governance readback](evidence/final-regression-20260908/repository-governance.json)
confirms main protection is disabled and the account has admin access. No settings
were changed. Requiring PR/CI and sensitive-path review and forbidding force pushes
remains a recommended repository-governance action, distinct from local code tests.
