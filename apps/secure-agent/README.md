# Secure Agent

Application layer for the [hackathon V4 target](../../docs/hackathon/final-hardening-goal-v4.md).
Python standard library only; no new authorization or evidence engine.

The application contract is `UserTask → ModelRouter → TaskPlan V2 → SkillRunner
→ ToolGateway → SecurityClient → existing SIQ API → controlled tool`.
The model receives task data and Skill descriptions, never admin, decision or
observer credentials. It cannot create Intent, provenance, approvals or effects.

`secure_agent.models.StepFunProvider` uses an explicitly configured endpoint,
model and optional key (local model endpoints may not require a key). It validates
JSON and typed outputs and fails without fallback. `FixtureProvider` is restricted
to explicitly selected test mode and is always labelled `fixture`, not StepFun.

Provider configuration:

```bash
export SIQ_MODEL_PROVIDER=stepfun
export SIQ_STEPFUN_ENDPOINT=https://api.stepfun.com/step_plan/v1
export SIQ_STEPFUN_MODEL=step-3.7-flash
# Supply SIQ_STEPFUN_API_KEY through the environment; never commit it.
```

Step Plan plans from approved public metadata; local Ornith handles research
and recipient context by default. CONFIDENTIAL raw input never goes remote.
The [private configuration](../../docs/hackathon/step-plan.md) is loaded without
putting keys in the repository. Use a complete environment bundle to override it.
To also use local planning explicitly:

```bash
export SIQ_MODEL_PROVIDER=ornith
export SIQ_ORNITH_ENDPOINT=http://127.0.0.1:8006/v1
export SIQ_ORNITH_MODEL=Ornith-1.5-35B-A3B-NVFP4
```

Ornith and StepFun share the strict transport and typed contracts but retain
distinct provider names in task state and model-call metadata. The archived
[ornith task](../../docs/hackathon/evidence/ornith-agent-20260908.json) used three
actual local inferences. Its token usage/timings are descriptive model metadata,
not security or semantic-quality evidence.

Every attempted model call retains safe diagnostics, including malformed JSON,
typed-contract rejection and transport failure. Terminal service snapshots expose
per-task `model_calls` even if planning failed before a result was produced.
See the [diagnostic contract](../../docs/hackathon/model-diagnostics.md).

For the persistent Linux/DGX service and browser Dashboard, run
`./scripts/hackathon/start.sh` (StepFun primary per operator instruction).
See [HACKATHON.md](../../HACKATHON.md) for paired operator access, scenario scripts
and isolated stop/reset. The service's `/hackathon/v1` API permits fixed-scope
task submission and snapshots; it does not proxy general SIQ admin APIs.
`./scripts/hackathon/demo-approval.sh` submits a task that waits for the paired
operator before starting the fixed `verify_report` subprocess. Original parameters
and current Intent are checked again by SIQ after approval; arbitrary shell
commands remain unavailable. The returned process metadata is REPORTED only.
`./scripts/hackathon/pair.sh` renews a one-use pairing code without resetting
tasks or sessions. Action snapshots include actual SIQ provenance readbacks,
including source type/trust and task/session scope; display metadata never grants
permission. See the [Demo evidence contract](../../docs/hackathon/demo-evidence-contract.md).

`./scripts/hackathon/demo-trifecta.sh` demonstrates a confidential fixture read,
an actual untrusted web response and subsequent egress denial in one execution
session. See the [stateful demonstration contract](../../docs/hackathon/lethal-trifecta-demo.md).

The [official StepFun API](https://platform.stepfun.com/docs/zh/api-reference/chat/chat-completion-create)
supports Chat Completions and JSON mode. Endpoint redirects are rejected so a
redirect cannot carry the credential to another service. Non-loopback endpoints
require HTTPS. Missing/invalid responses fail explicitly.

Run a complete isolated application task from the repository root:

```bash
GOTOOLCHAIN=go1.26.6 go -C apps/agentshield build -o "$PWD/.tmp/hackathon-bin/siq-agent-security" ./cmd/agentshield
PYTHONPATH=apps/secure-agent python3 -m secure_agent \
  --binary .tmp/hackathon-bin/siq-agent-security \
  --state-dir .tmp/hackathon-runs/first-demo
```

The CLI's default `demo` mode requires an explicitly configured real provider. Add `--mode test` for the
explicit fixture model. The state directory must be new for each invocation;
an existing SIQ state is never reused. This runs actual SIQ authorization,
three Skills, GitHub-shaped reads, a filesystem write, MCP contact lookup,
and a controlled HTTP message receiver. It sends no external email.
`--scenario` also supports `mcp-attack`, `same-value`, `fake-success`, and
`conflicting`. Fault scenarios are controlled fixtures. In fixture model mode,
attack scenarios deliberately select the MCP candidate to test SIQ's gate;
this is not a measurement of a real model's susceptibility.

Sources default to the controlled repository. For live GitHub use
`--github-endpoint https://api.github.com --repository OWNER/REPO --scope PATH`.
The adapter requests only the latest revision through GitHub's
[SHA response media type](https://docs.github.com/en/rest/commits/commits#get-a-commit),
then reads the selected files pinned to that revision. Contents are decoded
before SIQ Observe scans them. Anonymous API limits apply; an HTTP failure is
not replaced with fixture data.

The application prepares the model's report under a read-only task, then
commits exact file and HTTP payload digests in a new immutable execution Intent.
It rereads every source through SIQ and requires identical paths, revisions,
content and hashes before any write. This replay also preserves source taints
in the execution session. Completion uses that one execution Intent throughout.

Only the known directory/MCP routing scalar is represented in Observe by its
digest and signed provenance reference. Full source and report content, MCP
text and unknown fields remain scanned. Raw routing candidates still reach
the model; the model can choose a candidate but cannot change the precommitted
report after the MCP lookup. This scoped projection is not universal semantic
taint tracking. The SIQ-issued default V3 parameter constraints, restricted
operator issuer, exact workspace context and deployed Grant constrain actions;
heterogeneous resource domains are not combined into a false OR allowlist.

File verification comes from the existing SIQ host observer. Delivery evidence
comes from the controlled receiver's actual HTTP event, separately from tool
success. A missing receiver event leaves completion incomplete; substituted
bytes make it conflicting. This same-host test oracle is not an independently
administered production attestor.

Run application tests from the repository root:

```bash
GOTOOLCHAIN=go1.26.6 PYTHONPATH=apps/secure-agent python3 -m unittest discover -s apps/secure-agent/tests -v
```

Archive the five development scenarios with a fresh `--state-root`:

```bash
apps/control-api/.venv/bin/python scripts/hackathon/checkpoint.py \
  --binary .tmp/hackathon-bin/siq-agent-security \
  --state-root .tmp/hackathon-runs/checkpoint-1 \
  --out .tmp/hackathon-runs/checkpoint-1.json
```

This reuses the runtime-security receipt verifier (`cryptography` from the
existing development environment), records source hashes and validates effect
readbacks through SIQ. It is a five-scenario development checkpoint, not the
required twenty-task final benchmark. The later
[23-task Agent control suite and five-task ornith utility cohort](../../docs/hackathon/benchmark-report.md)
are implemented separately in `benchmarks/hackathon/`, including evidence
verification, explicit denominators and failed model attempts.

The gateway is an application enforcement boundary for the built-in Skills.
Python object visibility is not an OS sandbox: hostile installed Python code or
a same-UID process is outside this containment claim. Do not load or execute
arbitrary SKILL.md code. Local DGX Spark hardware and fixture-model application
runs are [evidenced](../../docs/hackathon/evidence/agent-e2e-20260908.json).
Dashboard scenarios are browser-tested; StepFun inference is deferred and full
competition acceptance remains pending.

V4 supports trusted `--output research|report|delivery` and
`--source-sensitivity PUBLIC|INTERNAL|CONFIDENTIAL|SECRET`. HTTP clients cannot
supply classification or authority overrides. The operator sets
`SIQ_SOURCE_SENSITIVITY` for the service. `SIQ_PUBLIC_RESEARCH_LOCAL=true`,
`SIQ_INTERNAL_REMOTE=false`, `SIQ_SECRET_LOCAL=false` are secure defaults;
values must be literal true/false. Invalid policy and unavailable local sensitive
inference fail closed. See the [egress contract](../../docs/hackathon/model-egress-v4.md).
