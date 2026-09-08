# DGX Spark deployment profile

The isolated Agent/SIQ/fixture service, existing local Web Demo Mode, start and
health scripts are implemented and locally exercised. Full competition acceptance
still requires improved real-model reliability and submission gates. The
[Agent benchmark](../../docs/hackathon/benchmark-report.md) now includes 23
control tasks and separate actual-provider cohorts. The latest ornith cohort
completed 5/5; earlier failures remain archived.
Approval continuation is exercised through the existing SIQ HOLD/recheck and
the browser operator panel; see the [approval checkpoint](../../docs/hackathon/approval-integration.md).

From the repository root:

```bash
./deploy/dgx-spark/start.sh
./deploy/dgx-spark/healthcheck.sh
./deploy/dgx-spark/preflight.sh --out .tmp/dgx-spark-environment.json
```

Per the operator's latest 2026-09-08 instruction, start defaults to Step Plan
`step-3.7-flash`, using the [private provider configuration](../../docs/hackathon/step-plan.md)
or a complete `SIQ_STEPFUN_*` environment bundle. Local ornith is the backup:
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

The current machine was identified as NVIDIA DGX Spark / GB10 / aarch64,
driver 580.126.09 and CUDA 13.0. See the
[recorded environment](../../docs/hackathon/evidence/dgx-spark/local-environment-20260908.json).
That initial record had no model configuration. The later
[ornith environment](../../docs/hackathon/evidence/dgx-spark/ornith-environment-20260908.json)
records reachable model, SIQ, Agent, Web and fixture services. Actual inference
is separately proven by the [model task](../../docs/hackathon/evidence/ornith-agent-20260908.json).
Preflight intentionally does not upgrade `deployment_verified` based on health alone.

For isolated real-tool execution and evidence export, follow the
[Secure Agent commands](../../apps/secure-agent/README.md). Every run uses a new
SIQ state directory and controlled message sink. Existing personal profiles are
not read or reset.
