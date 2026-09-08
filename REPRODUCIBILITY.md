# Reproduce SIQ Agent Security

Choose a track. A and B use explicit model fixtures plus the real SIQ runtime; they require no provider key or GPU. C uses real models and is optional. All commands run from this repository. First-time toolchain/package/browser installation needs network access. Results reproduce behavior, not identical timestamps, signatures or archive bytes.

Use Linux, Git, Go 1.26.6, Python 3.12+, Node 22/npm and uv. Python verifier dependencies are locked in apps/control-api/uv.lock:

```bash
(cd apps/control-api && uv sync --dev --locked)
```

## A — interactive fixture demonstration

Use a fresh clone: the existing launcher owns `.tmp/hackathon-profile/current` and refuses an existing profile. Its default demo mode invokes real models, so explicitly use `--mode test`:

```bash
bash scripts/hackathon/start.sh --mode test --port 47621
bash scripts/hackathon/healthcheck.sh
bash scripts/hackathon/pair.sh
```

Open the local `/demo` URL and enter the short-lived pairing code locally. Never publish that code or service.json. Try normal delivery, MCP injection, same-value provenance, and fake-success. Expect verified, blocked, blocked and incomplete, respectively. The UI distinguishes fixture planning from actual SIQ decisions and controlled receiver events.

```bash
bash scripts/hackathon/stop.sh
```

The reset script archives the owned profile. Inspect and stop it first; do not delete another running session to make these commands work. Browser automation uses `scripts/hackathon/browser-smoke.py --state-dir .tmp/hackathon-profile/current --out-dir <new-local-directory>` with Playwright/Chromium installed in the invoking Python environment. Pairing screenshots and logs require privacy review before sharing.

## B — fixed controls and offline verification

Choose previously nonexistent output/state directories for every attempt:

```bash
mkdir -p .tmp/research-bin
GOTOOLCHAIN=go1.26.6 go -C apps/agentshield build -o "$PWD/.tmp/research-bin/siq-agent-security" ./cmd/agentshield
apps/control-api/.venv/bin/python benchmarks/hackathon/run.py \
  --binary .tmp/research-bin/siq-agent-security \
  --state-root .tmp/my-research-controls \
  --out .tmp/my-research-results/controls.json
apps/control-api/.venv/bin/python benchmarks/hackathon/verify.py \
  .tmp/my-research-results/controls.json \
  --out .tmp/my-research-results/verification.json
```

The default cohort is all 23 fixed controls; `--case` is explicitly partial. Five benign tasks, thirteen unsafe-target tasks and eight provenance cases have different denominators. Failed/blocked statuses may be expected; read expectation violations and the verifier. State contains private local signing material and must not be uploaded. Reports contain public receipt keys: verification establishes internal consistency, not independent publisher identity.

Offline verification of a sanitized archived report uses the same verifier command after dependencies are installed. For the broader runtime suite, use `python3 benchmarks/runtime-security/run.py --suite smoke --out <new-report.json>` and `apps/control-api/.venv/bin/python benchmarks/runtime-security/evidence.py --suite smoke <new-report.json>`. The runner owns separate temporary state.

## C — optional real models / DGX

Read [the existing DGX runbook](deploy/dgx-spark/README.md) and [model configuration](docs/hackathon/step-plan.md); authoritative CLI options are in `scripts/hackathon/manage.py` and `deploy/dgx-spark/preflight.py --help`. Use `start.sh --mode demo --provider stepfun` only after configuring your private provider file. StepFun plans remotely; Ornith analyzes locally. No credentials belong in the repository or shell transcript.

`benchmarks/hackathon/run.py --cohort model-utility` is a separate real-model benign cohort. Record every attempt, model identifier, runtime/source digest, time, failure and cost; never merge it with control denominators. Repeat locality canary and local-failure tests only in your authorized environment. No new paid model run is implied by tracks A/B.

See [environment matrix](docs/research/environment-matrix.md) for actual validation. V5 real-model results remain historical; they are not new measurements of this research branch.

## Troubleshooting

An existing state/output path means choose a fresh path; do not overwrite evidence. For an occupied port choose another loopback port. For missing Python modules rerun locked uv sync. For missing embedded UI run the launcher's npm/build sequence; Python-only tests do not build a browser bundle. For browser errors install Chromium using the same Python environment. Failed verifier signatures or missing effects are failures to investigate, not values to patch in the report. Model connection failure in C must not enable confidential fallback to remote transport.
