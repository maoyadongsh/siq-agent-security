> Historical snapshot.
> For the current submission state, see: [docs/hackathon/final-submission-state.md](final-submission-state.md).

# Approval integration checkpoint — 2026-09-08

The application now pauses inside the report Skill for a real SIQ HOLD,
accepts an authenticated operator decision, rechecks the original action,
starts a fixed report-verification process only if approved, then continues
the original delivery workflow. It retains the same execution Intent and
source commitments. No new authorization or completion engine was introduced.

## Authority and process scope

- New admin request [grant-tool-approval/v1](../../packages/contracts/grant-tool-approval.schema.json)
  only tightens existing allowed tool facts in a pending Grant under its current
  revision. Signed `conditions.require_approval` participates in existing
  challenges, audit and runtime HOLD. PatchDesired preserves that condition
  when rebuilding the same tool. Unknown tools cannot be granted through this API.
- The closed [verify_report](../../packages/contracts/report-verification-tool.schema.json)
  operation has `file.read` and `process.exec` effects. Its only parameter is
  the authorized report path, with required V3 provenance and context. The
  executor runs a fixed isolated interpreter program without a shell, caller
  code, chosen executable or inherited credentials. It verifies the bounded
  file bytes against the committed report digest.
- Opaque exec/shell tools retain their unknown effect and fail closed under
  required Intent. This addition is not a general shell allowance or an OS sandbox.
- The process PID/exit/digest remain `REPORTED`. No independent process effect
  attestation is claimed. Existing file and receiver observers determine the
  report/delivery Completion requirements.

The operator HTTP endpoint accepts only the held action ID and a boolean
approve/reject choice. It cannot accept replacement parameters, select another
action, or access arbitrary SIQ admin APIs. The model receives no approval
callback or controller credential. The gateway retains serialized original
parameters, and a UI approval never substitutes for `/v1/hold-status`.

## Reproducible evidence

```bash
apps/control-api/.venv/bin/python scripts/hackathon/approval-checkpoint.py \
  --binary .tmp/hackathon-profile/siq-agent-security \
  --state-root .tmp/hackathon-state/new-approval-run \
  --out .tmp/hackathon-state/approval-result.json
```

The final case waits for the real daemon's sixty-second approval deadline.
[Archived result](evidence/approval-agent-20260908.json):

| Case | Outcome | Verification process / delivery |
| --- | --- | --- |
| approved | verified | process started, one message |
| rejected | blocked / hold_denied | neither |
| revoked after approval | blocked / hold_authority_changed | neither |
| replaced approval parameters | failed / hold_identity_mismatch | neither |
| daemon stopped after approval | failed / siq_unavailable | neither |
| real deadline expiry | blocked / hold_expired | neither |

These use actual SIQ, a real bounded child process, file/receiver services and
the existing receipt signature verifier. The model is explicitly FixtureProvider;
approval is supplied by an automated test operator using the admin API. This
does not represent a physical human participating in the automated tests.

[Browser evidence](evidence/dashboard-approval-20260908/result.json) includes
six sequential scenarios, an intermediate HOLD screenshot and an actual click
through the approval UI. The process remains unstarted while waiting. The
service test separately rejects unauthenticated approval, a substituted action
ID and extra replacement parameters.

## Actual model limitation

An ornith approval task failed in model response parsing with `json_duplicate_key`;
see [failure record](evidence/ornith-approval-failure-20260908.json). Strict parsing
was retained and no fixture fallback occurred. It is a utility/model-format
failure, not attack-blocking evidence. The earlier normal ornith task is still
valid evidence for its narrower completed workflow. Subsequent real ornith
approval tasks have completed, including the separately reported
[five-task utility benchmark](benchmark-report.md), which completes 4/5 tasks
overall and retains one planning-format failure. Its CLI approval actor is
explicitly automated; actual browser operator clicks have separate evidence.
