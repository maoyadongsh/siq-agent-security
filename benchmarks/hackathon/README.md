# Secure Agent E2E benchmark

This suite runs the real SecureApplication, three built-in Skills, SIQ daemon,
controlled GitHub/MCP server, filesystem and HTTP receiver. It reuses
`benchmarks/runtime-security/evidence.py` for signed receipts/effects and
`metrics.py` for existing decision metrics. It is an application runner and
metric projection, not another security engine.

`cases.json` fixes the corpus before execution. The `controls` cohort uses an
explicit FixtureProvider, including deliberately adversarial proposals and
transport/provenance mutations confined to this test harness. These cases
measure enforcement, not model susceptibility. The `model-utility` cohort runs
the five benign tasks with the explicitly configured real provider, no repair,
retry or fixture fallback. Model failures stay in the denominator. Both cohorts
use controlled source data and a local receiver; neither sends external email.

Each case has a new daemon state and task workspace. Benign tasks cover selected
documentation, path validation code, combined source review, Unicode source and
operator-approved process verification. Negative cases cover changed plan scope,
path and command proposals, MCP recipients, same-value origins, forged USER,
wrong-task/cross-session signed provenance, replayed PII/secret, changed sources,
revoked Intent, missing/conflicting delivery and approval mutation/revocation/
denial. Approval actors in this CLI are explicitly automated test operators.

Expectations are checked after collecting actual state and effects. A mismatch
is archived and exits nonzero; it never changes the observed outcome. The full
control suite requires every corpus case; a selected subset is labelled partial.
Artifacts record corpus/application/binary hashes, provider and all model calls.

Metrics always include numerator, denominator and population. Agent benign
completion uses **all attempted benign tasks**, including preparation failures.
Existing SIQ decision metrics retain their narrower populations. Unsafe action
attempt/materialization rates use negative tasks with a specifically identified
target tool, excluding effect-fault cases and rejected plans that never propose
a registered tool. D3 means entry into the actual tool adapter, which can still
fail; it is not proof of an effect. Receiver events and file hashes are separate
observations. Unauthorized/unknown effect rates use signed effect records, with
missing records disclosed separately. Absence of a record is never proof that
an unauthorized effect was absent. Verified effect rate uses committed effect
requirements; process metadata alone cannot satisfy one.

One pass is descriptive coverage, not a statistical model reliability claim.
Code review quality is not established by a verified file/delivery effect.

`verify.py REPORT` reuses the existing signature verifier, checks corpus coverage,
action/effect/Completion references and recomputes metrics. Optional `--out PATH`
writes a new verification artifact including the input report hash. The original
capture remains unchanged. An archived planning failure is valid evidence even
though the runner returns nonzero because its benign task did not complete.

```bash
GOTOOLCHAIN=go1.26.6 go -C apps/agentshield build -o "$PWD/.tmp/hackathon-bin/siq-agent-security" ./cmd/agentshield
apps/control-api/.venv/bin/python benchmarks/hackathon/run.py \
  --binary .tmp/hackathon-bin/siq-agent-security \
  --state-root .tmp/hackathon-benchmark/new-controls --out .tmp/hackathon-controls.json
SIQ_MODEL_PROVIDER=ornith SIQ_ORNITH_ENDPOINT=http://127.0.0.1:8006/v1 \
SIQ_ORNITH_MODEL=Ornith-1.5-35B-A3B-NVFP4 \
apps/control-api/.venv/bin/python benchmarks/hackathon/run.py --cohort model-utility \
  --binary .tmp/hackathon-bin/siq-agent-security \
  --state-root .tmp/hackathon-benchmark/new-model --out .tmp/hackathon-model.json
```
