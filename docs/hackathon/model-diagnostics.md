> Historical snapshot.
> For the current submission state, see: [docs/hackathon/final-submission-state.md](final-submission-state.md).

# Model-call diagnostics

The application records one diagnostic for each attempted Chat Completions call,
including calls rejected during JSON or typed-contract validation. Diagnostics
contain provider, configured model, operation (`plan`, `research`, `recipient`),
elapsed milliseconds, validated nonnegative integer usage counters, a recognized
finish reason or null, status (`accepted` or `failed`), and a safe error category
or null. `accepted` means the typed proposal parsed; it confers no authority and
does not mean the Agent task completed.

Unknown finish reasons, raw responses, prompts, exception details, HTTP bodies,
endpoint credentials and authorization headers are never copied into diagnostics.
Malformed envelopes fail with a bounded category. Duplicate JSON keys, unknown
typed fields and incomplete generations remain failures. There is no retry,
JSON repair, coercion, or provider fallback in this change.

Successful application results retain their existing `model_calls` field. The
operator service also exposes a per-task `model_calls` array on terminal task
snapshots, including preparation failures that have no application result.
Sequential tasks slice from their own initial call index; earlier calls are not
counted again. Existing archived runs are immutable historical evidence and are
not retroactively filled with inferred metrics.

Benchmark utility counts a malformed benign task as a task failure, separately
from SIQ denials and attack containment. Token counters are provider-reported
metadata, not independent hardware measurements.

## Local validation, 2026-09-08

The full application suite passes 60 tests. HTTP provider tests cover malformed
envelopes, duplicate keys, typed-field rejection, incomplete generations,
credential-preserving redirect refusal and untrusted usage/finish fields. The
actual SIQ/operator-service test runs two consecutive planning failures and
checks that each task records exactly its own failed call and no tool effects.

The [real ornith approval run](evidence/ornith-approval-current-20260908.json)
completed three accepted model calls and the full approval/report/delivery path
in about 32.3 seconds. Its 29 receipts verify and both effect records match SIQ
readbacks. The approval actor was an explicitly selected automated test operator;
the browser human-click path has separate evidence. The process PID is reported
metadata, not independently verified process evidence.

The [preceding setup attempt](evidence/ornith-approval-diagnostics-20260908.json)
used an older local binary without the approval endpoint and failed with
`siq_http_error` before any model call. Rebuilding the current binary resolved
that setup error. It is not a model inference failure or a security block.
The earlier [duplicate-key failure](evidence/ornith-approval-failure-20260908.json)
remains a real model-format failure; this change does not claim to fix it.

Reproduce one approval task after building the current SIQ binary:

```bash
SIQ_MODEL_PROVIDER=ornith \
SIQ_ORNITH_ENDPOINT=http://127.0.0.1:8006/v1 \
SIQ_ORNITH_MODEL=Ornith-1.5-35B-A3B-NVFP4 \
apps/control-api/.venv/bin/python scripts/hackathon/model-checkpoint.py \
  --binary .tmp/hackathon-bin/siq-agent-security \
  --state-dir .tmp/hackathon-runs/new-ornith-approval \
  --out .tmp/new-ornith-approval.json --approval-test-operator
```

The script archives typed-model and application failures as well as successes,
then exits nonzero for a task that did not reach verified completion.

## Tool observation text

The application sends structured tool-result JSON plus its decoded string keys
and values to the existing SIQ Observe text scanner. This preserves both the
structured representation and literal text such as `secret="value"` that JSON
escaping otherwise hides from a text pattern. This is an application transport
projection; the existing SIQ scanner still owns classification and session taint.
The routing-only provenance projection happens first, so raw routing scalars
are not reintroduced. Task/model result data and effect commitments are unchanged.
The combined observation is capped at 64 KiB of UTF-8, matching the SIQ API,
and fails explicitly on overflow.
