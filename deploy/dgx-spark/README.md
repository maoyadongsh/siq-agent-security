# DGX Spark deployment profile

The archived V4/V5 research deployment uses StepFun for public planning and verified local Ornith for source analysis
and recipient reasoning. The [V4 evidence index](../../docs/hackathon/evidence/INDEX.md)
contains actual hardware, local inference, zero remote confidential transport,
and separate small model cohorts with their earlier failures retained.

From the repository root, start an explicit fixture run first (no paid model calls):

```bash
./deploy/dgx-spark/start.sh --mode test
./deploy/dgx-spark/healthcheck.sh
./deploy/dgx-spark/preflight.sh --out .tmp/dgx-spark-environment.json
```

In the recorded 2026-09-08 configuration, start defaults to Step Plan
`step-3.7-flash`, using the [private provider configuration](../../docs/hackathon/step-plan.md)
or a complete `SIQ_STEPFUN_*` environment bundle. Local Ornith is the default research provider; to use it for planning too:
after managed reset, use `start.sh --provider ornith` and the defaults in
[env.ornith.example](env.ornith.example). Provider switches are explicit and
recorded; there is no silent fallback. `--mode test` selects FixtureProvider.
Use the printed loopback `/demo` URL and one-time pairing code. Detailed commands
and isolated stop/reset behavior are in [HACKATHON.md](../../HACKATHON.md).
If the code expires or another browser needs access, `./scripts/hackathon/pair.sh`
renews only the pairing code using the private local operator credential. It
preserves running tasks, existing sessions and audit state.

Preflight records actual DMI hardware, architecture, NVIDIA GPU/driver/CUDA,
RAM, OS, source SHA/dirty status and application file hashes. It checks fixture
and Skill presence. Optional service URLs and StepFun settings are documented
in [env.example](env.example); configure them in the environment. No API key
is written to the report. SIQ probes require local mode and block enforcement;
Agent, Web and fixture probes require the expected service identity.

`--require-ready` returns nonzero until hardware identity, the configured
ornith or StepFun model listing and every configured service probe pass. A model listing
does not prove inference, and preflight always leaves `deployment_verified`
false. Real model-driven E2E evidence is a separate acceptance requirement.

The machine recorded on 2026-09-08 was identified as NVIDIA DGX Spark / GB10 / aarch64,
driver 580.126.09 and CUDA 13.0. See the
[recorded environment](../../docs/hackathon/evidence/dgx-spark/local-environment-20260908.json).
That initial record had no model configuration. The later
[ornith environment](../../docs/hackathon/evidence/dgx-spark/ornith-environment-20260908.json)
records reachable model, SIQ, Agent, Web and fixture services. Actual inference
is separately proven by the [model task](../../docs/hackathon/evidence/ornith-agent-20260908.json).
Preflight intentionally does not upgrade `deployment_verified` based on health alone.

## Flagship runtime lock and doctor

The Hermes + OpenShell flagship candidate has a separate immutable input lock:

```text
deploy/dgx-spark/runtime-lock.v1.json
```

It binds the three OpenShell binaries, Hermes commit and integration patch,
candidate image/config digests, local model identity, company-scoped pool
binding, policy/mount identity, and the reviewed upgrade evidence. Run the
doctor from the security repository root:

```bash
SIQ_RESEARCH_ROOT=/home/maoyd/siq-research-engine \
SIQ_HERMES_ROOT=/home/maoyd/siq/hermes-agent \
  ./deploy/dgx-spark/doctor.sh \
  --out .tmp/flagship/dgx-spark-doctor.json
```

To use it as a cumulative gate, select the highest required level:

```bash
./deploy/dgx-spark/doctor.sh \
  --out .tmp/flagship/dgx-spark-doctor.json \
  --require-level business_completed
```

The report keeps six independent levels: configuration correctness, service
reachability, identity matching, security behavior, inference, and business
completion. A later level cannot hide an earlier failure. In particular, a
healthy running image can retain its recorded inference/business evidence while
the current source profile has drifted; cumulative gating then exits nonzero.

The doctor never sets `deployment_verified=true`. The current lifecycle remains
`NOT_PRODUCTION_CANARY`, and production approval is outside this command. It
does not read API keys, tokens, private keys, or raw report content. `--offline`
checks locked files and evidence while leaving live process, endpoint, and
container checks explicitly `unverified`.

The confidential Hermes 0.21 candidate has a second lock because it was
validated on an isolated gateway and has not replaced the active company pool:

```bash
./deploy/dgx-spark/candidate_doctor.sh \
  --out .tmp/flagship/confidential-candidate-doctor.json \
  --require-level promotion_boundary
```

`candidate_package_ready` covers the pinned candidate image, profile manifest,
classified policy/data controls, governed model proof, outage proof, and the
explicit no-promotion boundary. `current_environment_ready` additionally probes
the isolated gateway and the model currently served on ports 8006. This keeps a
reproducible candidate package valid when the operator intentionally serves a
different model, while reporting the live model mismatch instead of silently
claiming the candidate can run immediately. Use `--require-level
live_environment` only when the locked model must also be online now.

## Native candidate CI gate

The manual `dgx-spark-native-candidate` workflow is the hard gate for the
confidential candidate. It runs only on a self-hosted runner carrying all five
labels `self-hosted`, `Linux`, `ARM64`, `dgx-spark`, and `siq-openshell`.
Configure the absolute repository paths as the repository variables
`SIQ_RESEARCH_ROOT` and `SIQ_HERMES_ROOT`; both checkouts must already contain
their locked dependencies and be clean.

The gate policy is
`deploy/dgx-spark/native-candidate-gate.v1.json`. A single workflow batch must
provide all of the following before the final report can say `passed`:

- DGX Spark product identity, `aarch64`/`arm64`, an NVIDIA GB10 GPU, all runner
  labels, the checked-out GitHub SHA, and clean repository bindings;
- a freshly generated candidate doctor report with every level through
  `live_environment` equal to `pass`;
- verified primary gateway process identity and health plus a fresh resource
  audit with `operational_ready=true`, `gateway_status=healthy`, and proof that
  the SQLite payload column was not read;
- receipts for the security candidate contracts, Hermes AgentShield adapter,
  research OpenShell contracts, and Hermes native regression suites.

The security repository uses a locked baseline-ancestor binding because a Git
commit cannot contain its own commit hash. The workflow still requires its
actual clean HEAD to equal `github.sha`, and all locked artifacts retain exact
digests. Research Engine and Hermes use exact locked HEAD bindings. Evidence is
freshness-, candidate-, batch-, policy-, command-, and repository-bound.

Raw suite output remains in an owner-only runner temporary directory. The
workflow uploads only sanitized JSON receipts and reports. Missing reports,
missing suites, dirty trees, stale evidence, an unhealthy gateway, a model
mismatch, or a resource recovery hold all fail the job. Passing this gate means
the isolated candidate was verified; `production_eligible` and
`deployment_verified` remain `false`.

The current local worktrees intentionally do not pass this gate: they contain
the in-progress flagship changes, the live gateway still has the SP-02 recovery
hold, and the locked model is not online. The Hermes source also contains the
aiohttp `RequestKey` compatibility repair found by the CI-01 regression suite;
the candidate image and exact Hermes lock must be rebuilt/refreshed around that
repair before a native candidate run can pass.

For isolated real-tool execution and evidence export, follow the
[Secure Agent commands](../../apps/secure-agent/README.md). Every run uses a new
SIQ state directory and controlled message sink. Existing personal profiles are
not read or reset.

This profile is optional for [Secure Agent](../../apps/secure-agent/README.md)
research runs; the [personal client](../../apps/agentshield/README.md) does not
require DGX, a GPU or a real model. Model locality, execution authorization and
observed task completion answer different questions. Deployment health must not
be reported as confidential-data or security acceptance. Current OS and host
scope is maintained in [platforms/linux](../../platforms/linux/README.md).
