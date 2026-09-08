# SIQ Agent Security · Secure Runtime for Agent Skills

> Agent Skills define what agents can do. SIQ defines what they are allowed to do.

StepFun plans the task. DGX Spark performs local analysis. SIQ independently
authorizes consequential actions and separates tool reports from effect evidence.
The current target is [Final Hardening V4](docs/hackathon/final-hardening-goal-v4.md).
V4 engineering, exact-source PR CI, clean RC launch and a real 2–3 minute video
are complete: [final report](docs/hackathon/final-hardening-report.md). The RC is
unsigned and unpublished; main protection and competition upload remain external.

## Run the frozen demo story

Analyze a GitHub project, create a security report and deliver it to Alice:

```bash
./scripts/hackathon/start.sh
./scripts/hackathon/healthcheck.sh
```

Open the printed loopback URL and pair using the one-use code. StepFun uses the
existing private configuration; Ornith runs locally. No credentials go into the
browser or localStorage. Renew expired pairing with `./scripts/hackathon/pair.sh`.
Model identity, locality, task ID and source SHA appear in the dashboard.

The trusted operator selects the outcome; the model proposes the corresponding
Skills from a closed registry. Choose **只分析，不保存或发送** for research-only,
**分析并保存报告** for two Skills, or **正常交付** for all three. Equivalent commands:

```bash
python3 scripts/hackathon/manage.py research-only
python3 scripts/hackathon/manage.py research-report
./scripts/hackathon/demo-normal.sh
./scripts/hackathon/demo-mcp-attack.sh
./scripts/hackathon/demo-provenance.sh
./scripts/hackathon/demo-fake-success.sh
```

The main walkthrough is normal delivery → MCP injection → same value/different
provenance → fake success. Human approval is an optional fifth act:
`./scripts/hackathon/demo-approval.sh`, then Approve → SIQ Recheck → Execute.
Trifecta and conflicting-effect scenarios remain regression controls.
Use stop/reset only on this managed profile; reset archives its own previous state.

## Model and data boundaries

Default: **StepFun · REMOTE Planning**, **Ornith · DGX LOCAL Analysis**. PUBLIC
research may explicitly use the remote primary with `SIQ_PUBLIC_RESEARCH_LOCAL=false`.
Set `SIQ_SOURCE_SENSITIVITY=CONFIDENTIAL` for local-only service tasks. INTERNAL
remote use requires explicit policy; SECRET is denied unless explicitly enabled
for local processing. Private planning uses public templates and opaque aliases,
never private source bytes or operator free text. Failed local inference does not
send private data to StepFun. See the [model egress contract](docs/hackathon/model-egress-v4.md).

The four visible panels are CURRENT TASK, AGENT SKILLS, SECURITY DECISIONS and
EFFECT / COMPLETION. A research-only task may finish analysis while SIQ effect
Completion remains UNKNOWN: it did not request or verify a report/delivery effect.
A tool reporting success with no receiver event leaves delivery INCOMPLETE.

## Evidence in two clicks

Start at the [five-topic evidence index](docs/hackathon/evidence/INDEX.md): actual
Agent Skills, NVIDIA DGX Spark, StepFun, Security, and Effect & Completion.
It links directly to canonical raw files; earlier failures remain available.

| Measure | Latest V4 sample |
| --- | --- |
| Fixed control tasks | 23 |
| Benign completion | 5/5 |
| Unsafe target tool materialization | 0/13 |
| Provenance violation blocks | 8/8 |
| Latest StepFun planning + DGX analysis sample | 5/5 |
| Latest Ornith sample | 5/5 |

These are **small samples**. Earlier V4 4/5 cohorts are retained: the model chose
an untrusted MCP candidate and SIQ blocked the message. The updated recipient
planning prompt prefers the trusted directory; it does not weaken runtime checks.
Controlled fixtures measure runtime enforcement, not real-model attack success.

## Submission and limitations

The source and receiver in the repeatable demo are controlled fixtures; actual
model inference is labeled separately. Use `start.sh --mode test` for an explicitly
labeled FixtureProvider attack proposal. No external email is sent. A real model
may resist an injection; never turn that into a fabricated attack outcome.

See [architecture](docs/hackathon/architecture.md), [demo script](docs/hackathon/demo-script.md),
[submission checklist](docs/hackathon/submission-checklist.md), and
[limitations](docs/hackathon/limitations.md). Same-UID processes are not OS-isolated;
Python ToolGateway is not an OS sandbox; remote StepFun is an external trust boundary.
Policy-permitted PUBLIC analysis can leave the host. Effects are scoped to signed
file/controlled HTTP observations, not universal SaaS or semantic-review correctness.
