> Historical snapshot.
> For the current submission state, see: [docs/hackathon/final-submission-state.md](final-submission-state.md).

# Step Plan primary, ornith backup

The user has now configured Step Plan and selected it as the primary model.
This supersedes the earlier deferral; ornith remains the explicit backup.
The [official integration guide](https://platform.stepfun.com/docs/zh/step-plan/integrations/reasoning-api)
specifies the OpenAI-compatible base URL `https://api.stepfun.com/step_plan/v1`
and supports `step-3.7-flash`. We use the existing strict Chat Completions
provider, not the separate Messages API.

Local provider settings live outside the repository at
`~/.config/siq-agent-security/hackathon/providers.json` (directory 0700, file
0600). The file records primary `stepfun`, backup `ornith`, and each provider's
endpoint/model/key bundle. `SIQ_MODEL_CONFIG` can select another private file.
The application rejects symlinks, non-regular files, foreign-owned files and
group/world-readable configuration. No config contents or exception bodies are
logged. The model API key is a transport credential; the model never receives
SIQ authority credentials.

Complete environment configuration remains supported. If any provider-specific
environment setting is supplied, it is treated as a separate bundle: the
application never supplies a private-file key to an overridden endpoint.
Missing required environment fields therefore fail instead of silently mixing
configuration. The default demo provider is now StepFun. Use
`scripts/hackathon/start.sh --provider ornith` after the managed reset for an
explicit backup switch. There is no automatic retry or silent provider fallback;
failed StepFun attempts stay visible and provider identity remains truthful.

The private file is excluded by location from source snapshots and RC packages.
Public artifacts contain endpoint/model identity and safe per-call diagnostics,
not the API key. Actual Step Plan validation results are recorded separately
from earlier ornith and FixtureProvider results.

The [first actual Step Plan checkpoint](evidence/step-plan-first-20260908.json)
completed in 70.91 seconds: three accepted calls, 26 verified signed receipts
and two SIQ effect readbacks. Sources and delivery were controlled fixtures;
this is an end-to-end provider/application validation, not a general reliability
claim. The separate [five-task cohort](evidence/benchmark-20260908/step-plan-primary.json)
completed **4/5**. The code-review task failed during research with
`model_request_timeout` after 60.08 seconds; it is retained in the denominator.
The [existing verifier](evidence/benchmark-20260908/step-plan-primary-verification.json)
checked 103 receipts and eight effect envelopes. No retry or backup substitution
was used. Further primary-model timeout/reliability work remains.

For the known `step-3.7-flash` model, the next request profile uses its documented
`reasoning_effort=low` and generation limits of 3072 plan, 4096 research and 1024
recipient tokens. This selected-file demo trades longer reasoning for bounded
proposal generation; it does not claim equivalent semantic review quality.
The existing 60-second timeout and strict truncated-response rejection remain.
Other StepFun model names retain their existing request format. The new profile
must be evaluated in a separate cohort, keeping the original timeout evidence.
75 Agent tests pass after private-configuration integration, including rejection
of permission errors, symlinks and credential mixing across endpoint overrides.
The [current managed demo health](evidence/dgx-spark/step-plan-demo-health-20260908.json)
reports StepFun for both Agent and Web at `http://127.0.0.1:47621/demo`.

## Low-effort cohort and current primary

The [low-effort cohort](evidence/benchmark-20260908/step-plan-low.json) completes
5/5, with 15 accepted calls and separately verified receipts/effects in
[verification output](evidence/benchmark-20260908/step-plan-low-verification.json).
Task P50 is 15.68 seconds and P95/P99 are 33.56 seconds in this five-task sample.
The [performance projection](evidence/dgx-spark/performance-step-plan-low-20260908.json)
retains separate model and SIQ component populations. The old 4/5 cohort remains
archived. Eighteen provider tests pass after the profile change. The managed
primary demo now uses this profile. A fresh [DGX preflight](evidence/dgx-spark/step-plan-environment-20260908.json)
passes --require-ready for hardware, actual Step Plan model listing and all four
service probes. Model weights/digest remain remote-provider information, not
locally verified weights. Inference is proven by the separate actual tasks.
