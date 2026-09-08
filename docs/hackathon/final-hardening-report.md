> Historical snapshot.
> For the current submission state, see: [docs/hackathon/final-submission-state.md](final-submission-state.md).

# Final Hardening V4 engineering report

V4 implements trusted model routing and constrained Skill composition in the
existing runtime, with independently observed effects deciding Completion.
This report separates the frozen executable source from subsequent evidence-only
commits. Official publication, publisher signing and video upload remain external.

## A. Source and scope

- starting_sha: `9b4aaeae1a089b54fbbc50c33cdb72616be2b1b1`.
- final_sha / frozen executable source: `4da9e9e0a04c56620d101a583307b299b8484372`.
- branch: `codex/hackathon-final-hardening-v4`; PR [#5](https://github.com/maoyadongsh/siq-agent-security/pull/5) targets `codex/dgx-spark-hackathon-v3` and remains unmerged.
- Follow-up commits contain completion evidence/docs and a narration-only media utility; the runtime/UI remain frozen. Main and repository settings were not changed.

## B. Model routing

Remote StepFun `step-3.7-flash` receives approved public planning metadata.
Ornith `Ornith-1.5-35B-A3B-NVFP4` on DGX Spark performs research and recipient
reasoning by default. Trusted PUBLIC/INTERNAL/CONFIDENTIAL/SECRET classification
is checked before transport. Private remote planning uses public templates and
opaque aliases; confidential source/question bytes require verified local DGX
inference. SECRET defaults to deny. Local unavailability fails closed, without
silent fallback. Operator switches are rechecked and audited. Diagnostics expose
provider/locality/classification/digest/time/status without raw private payloads.
[Policy and negative cases](model-egress-v4.md).

## C. Agent Skills

TaskPlan V2 selects one, two or three registered Skills under the trusted requested
outcome. Dependencies are validated before tools. Unknown, duplicate, reordered,
missing, excessive and incomplete plans are rejected; no automatic repair or
invented shell/approval/signing Skill. Registry metadata includes schemas, tools
and security requirements. Selected/completed Skills are actual runtime state.
Research-only has no write or delivery and retains UNKNOWN effect Completion.
[Contract](dynamic-plans-v4.md).

## D. Security

The existing signed Intent, trusted Context, parameter Provenance, Runtime gate,
receipt chain, Effect observers and Completion kernel remain the authority.
Preparation is read-only; execution commits exact bytes and rechecks source replay.
Tool success is separate from observed file/receiver evidence. Deterministic
controls passed 23/23, benign 5/5, unsafe execution 0/13, provenance blocking 8/8.
MCP substitution, same-value/different-origin, fake success, conflicting effects,
approval/revocation and stateful trifecta are retained. Fixtures exercise actual
SIQ and tool boundaries; they are not claims about real-model attack susceptibility.

## E. DGX

Actual machine: NVIDIA DGX Spark, GB10, aarch64, Ubuntu 24.04.4, driver
580.126.09, CUDA 13.0, 130663591936 bytes RAM. Hardware identity, endpoint listing
and actual inference are separate observations. Real PUBLIC and CONFIDENTIAL
research-only tasks verified that the canary was received locally and absent
from remote transport. Latest independent mixed StepFun/Ornith and all-Ornith
cohorts each completed 5/5. Earlier 4/5 cohorts remain: local recipient reasoning
selected MCP origin and SIQ denied it. Model-weight digest remains unverified.

## F. Validation and remote CI

Local validation: 100 Agent tests; 650 Control API tests; 10 model schema tests;
11 Web tests, normal and local builds; Go test/race/vet; govulncheck; npm/pip
audits; PostgreSQL migration to head; 55 additional repository/adapter checks;
calibrated source gitleaks; 12 package/evidence tests; nine browser scenarios.

Frozen-source pull_request runs:

- [ci #34227071455](https://github.com/maoyadongsh/siq-agent-security/actions/runs/34227071455): success; 28 successful jobs.
- [runtime-security #34227071411](https://github.com/maoyadongsh/siq-agent-security/actions/runs/34227071411): success; 2 successful jobs.

30 mandatory jobs passed; the nightly-only job was correctly skipped for a PR.
The runtime-security contracts job includes Secure Agent/package tests, scenario
schemas, complete competition controls and independent signature/effect verification.
The Web job includes tests and both builds. [Full jobs and steps](evidence/final-hardening-v4/remote-ci.json).

All records retain their actual source identity. Incremental dirty checkpoints
are not relabeled as clean candidate runs. Canonical raw records are linked from
the [five-topic evidence index](evidence/INDEX.md).

## G. Clean release candidate

Candidate: `siq-agent-security-v0.3.0-rc.1` from clean detached source `4da9e9e0a04c56620d101a583307b299b8484372`.
Archive SHA256: `12b9de90082f72f1dee2198ac9fe0b3e0536e555d6f2107c8221c9f5c08b6e90` (84160374 bytes).
Local archive: `.tmp/final-hardening-v4/rc-v3/siq-agent-security-v0.3.0-rc.1.tar.gz`.
[Artifact/identity inventory](evidence/final-hardening-v4/rc.json),
[SBOM](evidence/final-hardening-v4/rc-artifacts/sbom.cdx.json),
[source identity](evidence/final-hardening-v4/rc-artifacts/source-info.json).

The clean-source guard passed before/after rebuilding locked Web assets. Four
binaries were built with Go 1.26.6; calibrated candidate gitleaks passed. The
archive was extracted and launched via its own launcher; an actual StepFun/Ornith
task completed with independently verified signed receipts/effects. Package hashes
remained unchanged after execution. [Extracted launch](evidence/final-hardening-v4/rc-checkpoint.json).

Checksums verify bytes, not publisher identity. Existing historical v0.2.0
signatures are retained and do not sign this RC. No test key is presented as a
publisher key. Linux extracted launch is exercised; other targets are cross-builds,
not native production certification. No tag is overwritten and no stable release
or official RC publication is performed.

## H. Frozen Demo and video

Nine browser scenarios exercise normal, research-only, research+report, MCP,
same-value, fake success, conflicting effects, approval and trifecta. The four UI
panels show actual selected Skills, hardware/locality, source identity, decisions,
provenance and effects. Same mailbox comparison uses two actual recorded decisions.

The accepted raw 170.00-second recording is saved at
`.tmp/final-hardening-v4/video-v3/siq-v4-demo.webm`.
Video SHA256: `c2e68238c9d3c4ecefd01d4e08f786df09792cdc88fd0c5091288b0450609a4c`.
[Metadata and independent review](evidence/final-hardening-v4/video.json).
The raw capture has no audio, cuts or speed changes; captions explain actual UI data. Video is not
uploaded. Actual stream duration and sampled visual checks are in the review.

The first recording stopped on an automation race between two adjacent blocked
tasks. The runtime outcomes remained correct. The task-ID synchronization fix
received fresh PR CI, a new clean build and a new full recording.
[Failed attempt retained](evidence/final-hardening-v4/video-first-attempt.json);
[actual adjacent-task regression](evidence/final-hardening-v4/recording-sync-check.json).

The second recording failed visual acceptance: its normal-task summary displayed
missing even though SIQ delivery evidence was verified. The summary now derives
from the SIQ delivery requirement; normal/conflicting/fake-success browser checks
cover the distinction. Fresh CI/build/recording followed.
[Second attempt retained](evidence/final-hardening-v4/video-second-attempt.json).

The requested Chinese presentation is now available at
`.tmp/final-hardening-v4/video-zh/siq-v4-demo-zh.mp4` (169.92 seconds,
H.264/AAC). It adds synthetic Mandarin narration and Chinese/English subtitles
in a new band below the complete original frame; the original timeline and UI
are retained. SHA256: `a9e003f47051b1ddf367b50dcf3a1e7293b7f7786f241cb7028b1a5bc8ea5430`.
[Chinese video metadata and review](evidence/final-hardening-v4/narrated-video-zh.json),
[bilingual subtitles](evidence/final-hardening-v4/subtitles.zh-en.srt),
[public narration script](demo-narration-zh.json). All twelve speech clips fit
their windows at native speed. Original-area frame SSIM is 0.998636 after
H.264 encoding. Only the public narration script was sent to the speech service.
The narration utility is a presentation companion, not part of the frozen runtime
candidate. The raw recording and its signed evidence remain unchanged.

[Runbook](demo-script.md). Real-model acts and explicit FixtureProvider attack
controls stay labeled. Approval is available as an optional live act and passed
the browser regression. No decision is fabricated or relabeled for recording.

## I. Measured performance

| Population | N | P50 ms | P95 ms | P99 ms |
| --- | ---: | ---: | ---: | ---: |
| StepFun-plan / Ornith-analysis complete tasks | 5 | 7212.76 | 11391.61 | 11391.61 |
| Ornith-only complete tasks | 5 | 5375.67 | 8331.98 | 8331.98 |
| StepFun planning calls in mixed cohort | 5 | 4065.30 | 4705.51 | 4705.51 |
| Ornith calls in mixed cohort | 10 | 260.43 | 6384.73 | 6384.73 |
| Runtime decision component | 100 | 11.57 | 12.83 | 13.63 |
| Effect processing component | 100 | 6.01 | 6.71 | 7.00 |

These are newly measured V4 populations; whole tasks, model transport and Go
components measure different scopes. V4 retains the same 23 control cases and
unsafe-action/provenance denominators; the unknown-Skill reason changes to the
V2 structured category. The model topology changed, so historical latency is not
a controlled before/after speedup. Failures remain archived; small percentiles
are descriptive, not an SLA or statistical reliability guarantee.

## J. Residual risks and external handoff

- Same-UID processes are not OS-isolated; built-in Python ToolGateway is not an OS sandbox.
- Remote StepFun is an external trust boundary; PUBLIC source analysis may be remotely permitted by policy. Classification depends on trusted operator correctness.
- No general semantic provenance, universal SaaS effect verification or universal MCP security is claimed. Controlled receiver observations are same-host and scoped.
- No full multi-agent delegation, Windows production certification or production HA is claimed.
- Small model cohorts are not statistical or semantic-quality guarantees. Model endpoint availability and public GitHub quotas can fail.
- Main protection, official publisher signing, public release and competition video upload remain explicit external/manual items. [Exact governance steps](repository-governance-actions.md); tasks are not falsely marked complete.
