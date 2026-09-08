# Hackathon V3 development progress

Updated 2026-09-08 on `codex/dgx-spark-hackathon-v3`.
Starting SHA: `e309655915562a27cb98df851c1e46e922563d47`.
Implementation commit: `a8dfdeb85287ee2ce476f9c94127c77bde79f2a4`.
The user authorized committing and pushing this work to the existing development
branch; subsequent documentation records delivery without rewriting historical evidence.
The complete goal remains [Master Plan V3](master-plan-v3.md).
Latest operator steering: **StepFun primary, local ornith explicit backup**.
Both have real inference evidence. Earlier deferrals and failed cohorts below
are historical snapshots, superseded by this current table and the final report.

| Work item | State | Evidence / remaining work |
| --- | --- | --- |
| COMP-00 | implemented | [Repository audit](current-state.md), synchronized clean main and requested development branch. |
| COMP-01 | CLI/service implemented and exercised | Actual three-Skill tasks, live state snapshots, credential-separated loopback service, one-time operator pairing and idempotent submissions. Concurrent tasks are rejected; sequential tasks are validated in one daemon. |
| COMP-02 | locally evidenced | Three SKILL.md packages pass validation and actual SIQ admission as admit_with_conditions. Real Agent runs execute all three Skills; local RC contains them. Cross-builds are not native OS installation proof. |
| COMP-03 | StepFun primary and ornith backup evidenced | Both latest five-task cohorts complete 5/5 with 121 verified receipts and ten effect envelopes each. Earlier failures retained; no hidden provider failover. Private configuration is outside the repository. |
| COMP-05 | integration and regression evidenced | Admission/Grant, Intent/context/provenance, decision/Observe and file/network observers run end to end. Existing SIQ HOLD/resolve/recheck resumes a real fixed verification process; six approval controls and full stateful trifecta are archived. |
| COMP-06 | implemented; fixture-model evidenced | Authenticated loopback GitHub/MCP/sink services, trusted contacts and real receiver event oracle; five scenarios archived. This same-host controlled oracle is not independently administered production attestation. |
| COMP-04 | actual DGX profile evidenced | Actual DGX/GB10 identity, StepFun and ornith inference and SIQ/Agent/Web/fixture health archived. Start/health scripts and extracted candidate 1 launch work on Linux arm64. Remote model weights/digest are not independently attested. |
| COMP-07 | seven browser scenarios passed | Existing local SPA `/demo`: provenance source/trust/scope/digest readbacks, same-value explanation, effects, model diagnostics, approval and full trifecta. Renewed pairing preserves history and sessions; no page errors, mobile overflow or localStorage credentials. |
| COMP-08 | core automation exercised | start/health/stop/reset and normal/attack/provenance/fake-success/approval scripts implemented. Approval submission waits for paired-operator input in the UI. Reset archives only owned profile state after process identity checks. |
| COMP-09 | implemented and evidenced | 23 actual Agent control attempts satisfy reviewed expectations; separate StepFun and ornith utility cohorts each complete 5/5. Earlier 4/5 cohorts and all failures remain archived separately. |
| COMP-11 / 12 | locally evidenced, benchmarked and displayed | Provenance controls, fake success and conflicting effects run through actual Agent/SIQ/sink and Dashboard. SIQ assertion readbacks expose source/trust and scope; same-value MCP remains denied and revoked-source display becomes unavailable. |
| COMP-13 | scoped performance evidenced | Actual DGX component measurements and separate model-call/task populations have P50/P95/P99. Latest StepFun task P50 15.683 s / P95 33.562 s; latest ornith P50 5.574 s / P95 9.813 s. Five tasks each, not an SLA. |
| COMP-10 / 14 | local submission and candidate preparation evidenced | [Final report](final-engineering-report.md), 649 Control API / 79 Agent / 10 package-proof tests, Go matrix, native harnesses and calibrated scans. Candidate 2 passed actual extracted StepFun launch with 26 receipts/two effects. Unsigned/unpublished; external boundaries disclosed. |

## Integration finding and correction

A signed, trusted `alice@company.example` recipient was rejected even in a fresh
session: the old generic PII scanner treated the recipient mailbox as leaked
payload. This was not caused solely by earlier negative tests. The correction
in the existing receipt engine classifies only proven V3 message routing fields
separately for the new PII scan. It does not clear state or omit those fields
from secret/threat scans, parameter digests or resource checks. The exact rule
is in the appended [development specification](../agentshield-dev-spec-v1.md).

Real daemon tests now allow that trusted mailbox and deny the identical mailbox
with MCP origin. Focused Go cases additionally reject body email/SSN/secret,
pre-existing PII, untrusted routing and optional constraints. Observe still
propagates PII, and a later action remains denied.

Sequential service tasks exposed a second integration defect: different Grants
for the same admitted Skill published distinct selectors at the same content-hash
policy ID/version. The immutable state writer correctly rejected that collision.
Initial desired policy IDs now include the Grant ID, matching PatchDesired's
fallback namespace; existing signed references and policy files are unchanged.
Go tests cover different subjects/platforms, and the real HTTP service test runs
normal → attack → fake-success with three distinct Grants in one daemon.

## Validation performed

- `GOTOOLCHAIN=go1.26.6 PYTHONPATH=apps/secure-agent python3 -m unittest discover -s apps/secure-agent/tests -v`: **69 passed**, including 15 application E2Es, 8 actual HTTP service tests and 5 lower-level SIQ daemon cases. These are not 67 full model-driven benchmark tasks.
- `apps/control-api/.venv/bin/ruff check apps/secure-agent deploy/dgx-spark/preflight.py scripts/hackathon`: passed.
- `GOTOOLCHAIN=go1.26.6 go -C apps/agentshield test ./...`: passed.
- `GOTOOLCHAIN=go1.26.6 go -C apps/agentshield test -race ./...`: passed.
- `GOTOOLCHAIN=go1.26.6 go -C apps/agentshield vet ./...`: passed.
- Go cross compilation: Linux amd64/arm64, macOS arm64 and Windows amd64 passed.
- Selected Python Schema / Provenance / Authority Effect / new approval contract tests: **140 passed**.
- Web: `npm ci`, `npm run build`, `npm run build:local`, and `npm run test`: passed (11 tests).
- `scripts/hackathon/browser-smoke.py`: six actual browser scenarios passed, including HOLD → operator click → real process → verified delivery; screenshots and assertions archived.
- `scripts/hackathon/approval-checkpoint.py`: six actual SIQ approval/recheck cases passed, including actual 60-second expiry and daemon shutdown, with verified receipt chains. The test operator and model are explicitly synthetic; the tools/daemon/process/receiver are real.
- Profile: actual start → health → stop → reset → start exercised. Reset retained audit archives, with a fresh active state.
- Skill creator validation for all three packages: passed.
- Actual SIQ `admit` with isolated state for all three packages: `admit_with_conditions`.
- Existing CI Action pin check and `git diff --check`: passed.
- The runtime-security workflow now includes the application lint and tests; this local edit is not a completed remote CI run.

## Application evidence checkpoint

[Five archived runs](evidence/agent-e2e-20260908.json) were regenerated by
`scripts/hackathon/checkpoint.py` using a fresh isolated state root. The exporter
reuses the existing runtime-security Ed25519 receipt verifier, validates every
effect through SIQ readback, and records the current application/fixture/Skill
file hashes alongside the dirty starting SHA. These runs use `FixtureProvider`
explicitly; they do not measure StepFun susceptibility or model quality.

| Scenario | Actual task state | Sink messages |
| --- | --- | --- |
| normal | verified (report and delivery) | 1 |
| mcp-attack | blocked: provenance_source_not_allowed | 0 |
| same-value | blocked: provenance_source_not_allowed | 0 |
| fake-success | incomplete | 0 |
| conflicting | conflicting | 1, substituted bytes |

Additional application tests reject changed sources after commitment, model
report-path substitution, revoked authority and replayed source PII. The
two-phase workflow precommits report/HTTP digests, rereads all pinned source
bytes under the execution Intent, and preserves source scanning in that session.
Only explicit routing values use signed-reference/digest observations; decoded
source text, report bodies and other MCP data remain scanned.

[DGX environment](evidence/dgx-spark/local-environment-20260908.json) confirms
NVIDIA DGX Spark, GB10, aarch64, driver 580.126.09, CUDA 13.0. StepFun endpoint,
model and key were unconfigured in that initial capture. Live
GitHub validation hit anonymous API rate limiting (HTTP 403, remaining 0) after
switching revision lookup to the SHA-only endpoint; no live-source pass is claimed.

## Real ornith and Dashboard checkpoint

The user subsequently authorized local ornith. The discovered service advertises
`Ornith-1.5-35B-A3B-NVFP4` at `http://127.0.0.1:8006/v1`. Its first inference
encountered a SGLang NCCL `nvmlInit_v2()` error and the existing service auto-restarted;
no model-service configuration was changed. After reload, an actual task passed.
The later reproducible [ornith checkpoint](evidence/ornith-agent-20260908.json)
completed three real model calls in about 30.3 seconds end to end, with verified
report and delivery. It includes returned token usage, source code hashes,
the generated report and verified SIQ receipt chains/effect readbacks. This is
one controlled task, not a quality claim or statistical performance benchmark.

[Environment health](evidence/dgx-spark/ornith-environment-20260908.json) now records
actual DGX hardware plus reachable ornith/SIQ/Agent/Web/fixture services. The
active local demo uses ornith and is served at `http://127.0.0.1:47621/demo`.
[Browser evidence](evidence/dashboard-20260908/result.json) covers all five
deterministic scenarios in one test-mode service. Generated reports remain
model proposals; Completion proves scoped effects, not semantic review accuracy.

## Approval checkpoint

[Integration details](approval-integration.md) document the new admin-only
approval-condition request and closed `verify_report` descriptor. Existing
Grant/challenge/audit and receipt HOLD/recheck enforce authorization; arbitrary
shell normalization remains fail-closed. The fixed report checker starts an
actual isolated subprocess, but its PID/digest is only REPORTED, not independent
process-effect evidence. [Six controls](evidence/approval-agent-20260908.json)
prove approved execution plus no process/delivery on rejection, revoked Intent,
parameter substitution, daemon unavailability and actual expiry.
[Updated browser run](evidence/dashboard-approval-20260908/result.json) also
passes the approval UI in the existing local SPA.

The separate [ornith approval attempt](evidence/ornith-approval-failure-20260908.json)
failed at planning with `json_duplicate_key`, before any tool action. This is
an actual model-format/utility failure, not an attack-blocking success. No raw
malformed output was logged and no fixture fallback was used. Model-format
reliability is an open item for the coming normal-task utility benchmark.

After adding [per-attempt model diagnostics](model-diagnostics.md), a subsequent
[actual ornith approval task](evidence/ornith-approval-current-20260908.json)
completed in about 32.3 seconds: three accepted calls, an explicitly automated
approval operator, a real fixed subprocess, 29 verified receipts and two effect
readbacks. A preceding stale-binary setup failure is also retained separately.
Neither a later success nor improved diagnostics erases the earlier format
failure. No model service settings or retry behavior were changed.

## Next implementation steps (do not replace the full goal)

1. Structured ornith requests and direct-output generation now complete 5/5 in the latest small cohort; retain earlier failures and broaden model evaluation.
2. Expand real-model adversarial evaluation and operational diagnostics; the 23 control cases measure enforcement, not ornith attack susceptibility.
3. Live-source validation now succeeds. Finish submission material and candidate packaging; provenance UI and the scoped DGX performance report are evidenced.
4. Run final full acceptance checks. StepFun setup remains deferred per user instruction; use ornith for ongoing actual inference.

No production/demo fixture fallback, external email, release, merge, push or
actual StepFun inference or full deployment verification has been performed. Same-process built-in Python
Skill boundaries are not an OS containment claim. This is an intermediate
checkpoint, not the final engineering acceptance report.

## Full application benchmark checkpoint

The [benchmark report](benchmark-report.md) records 23 controls plus five actual
ornith tasks, distinct security/utility denominators and all initial failures.
The first pass found escaped-secret observation loss and report-prose resource
false positives. Both paths are corrected with actual SIQ regression tests.
Current control outcomes are 23/23; ornith benign completion is 4/5, with a
`contract_fields_invalid` planning failure retained. Six benchmark verifier tests
and 21 existing benchmark tests pass. Latest Go all/race/vet/cross-build and six
browser scenarios pass after these fixes. The active ornith profile is refreshed
with the new code; its previous state is retained in the owned audit archive.

## Provenance UI, re-pairing and DGX performance

[Demo readback evidence](demo-evidence-contract.md) now covers SIQ-returned
assertion source, trust, digest, derivation and task/session scope. Display reads
occur after allowed tool execution and do not insert another HTTP round-trip
between allow and tool entry. Issuer-revocation readback is unavailable, not a
fabricated trust label. Browser tests verify the same-value MCP explanation,
persistent action-error messages and renewed pairing with both browser sessions
still able to read the original task history. The local `pair.sh` command is
exercised against the refreshed ornith service.

The [DGX performance report](dgx-performance-report.md) records separate actual
Agent/model and SIQ component distributions. It verifies input evidence and
recalculates percentiles, preserves the failed planning attempt, and does not
claim independent GPU timings or production SLA.

[Live GitHub status](live-source-validation.md): the SHA endpoint is reachable
again (HTTP 200), but a configured live-source ornith planning call failed at
about 60 seconds, before any tool action. This additional failure is archived
separately from the fixed five-task utility cohort. Live-source completion is
still unverified; model transport/format reliability remains the next open item.

## Structured ornith and repository acceptance checkpoint

The [structured-generation report](structured-model-output.md) records the actual
SGLang protocol/template inspection and two new five-task cohorts: schema-only
4/5 (4096-token research truncation retained), then direct-output 5/5 with 15
accepted calls. Strict host validation still rejects malformed/truncated output.
The latest cohort verifies 121 receipts and ten effect envelopes. StepFun remains
deferred. The current managed demo is refreshed to direct-output ornith.

The [live GitHub checkpoint](live-source-validation.md) now succeeds: three
model calls, 22 verified signed receipts, two effect readbacks, 21.90 seconds.
This supersedes the earlier pending status without deleting its rate-limit and
transport failures. Contacts and delivery remain controlled.

[Repository regression](repository-regression.md) now covers 62 passing command
checks plus 648 Control API tests, 69 Agent tests, 17 final-provider follow-up
tests, isolated PostgreSQL migration, reachable-vulnerability scan and existing
runtime/recovery evidence verification. It is local execution, not remote CI.

Remaining work: broader real-model adversarial evaluation, native platform/Skill
installation acceptance, source/secret audit, submission/final engineering
report and RC preparation. Do not mark the overall goal complete yet.

## Step Plan primary and RC-preparation checkpoint

The user supplied Step Plan credentials and selected StepFun as primary, with
ornith as explicit backup. Private configuration is outside the repository and
requires restrictive ownership/permissions. Complete environment overrides do
not inherit a file-based credential for another endpoint. The current managed
demo reports StepFun for Agent/Web. The first full Step Plan task verified
report/delivery with 26 receipts; the separate five-task cohort completed 4/5
with one 60-second research timeout retained. Its verifier checks 103 receipts
and eight effect envelopes. See [Step Plan](step-plan.md). All 75 Agent tests
and nine model/configuration schema tests pass. Primary reliability work remains.

RC preparation discovered that the old Gitleaks configuration had no default
rules. Its old zero-findings result is invalid acceptance evidence. Default
rules, exact reviewed fixture exceptions and a real-scanner calibration are
now active; calibration also rejects the old empty-rule configuration. The
latest hashed source snapshot passes with zero findings. 90 threat-analysis
tests pass after a semantics-preserving fixture-literal rewrite. CI includes
scanner calibration. See [regression details](repository-regression.md).

The [RC contract](rc-preparation.md) and `scripts/hackathon/package_rc.py` draft
are present, but no RC archive has been built or accepted yet. Launcher, package
verification tests, archive validation and remaining final acceptance are still
required. The overall goal remains active.
