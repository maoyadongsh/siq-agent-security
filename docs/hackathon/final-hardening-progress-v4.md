# V4 implementation progress

Updated 2026-09-08. Goal: [complete V4 engineering delivery](final-hardening-goal-v4.md).
Branch: `codex/hackathon-final-hardening-v4`, baseline
`9b4aaeae1a089b54fbbc50c33cdb72616be2b1b1`. This is an incremental checkpoint,
not the final engineering report or an RC acceptance declaration.

## Implemented checkpoints

- `cbab5de`: original requirements, current-state audit and complete task inventory.
- `35a45e0`: immutable source sensitivity; remote/local provider capabilities;
  routing of research and recipient context; private planning aliases; transport
  gate and redacted per-call metadata; no timeout fallback and audited switches.
  [Egress contract](model-egress-v4.md) documents trusted classification limits.
- Current implementation: [TaskPlan V2](dynamic-plans-v4.md), closed dependencies,
  one/two/three-Skill execution, scope-limited Intent, research-only without invented
  effect verification; actual selected/completed Skills in the existing dashboard.
- Runtime hardware/locality card and safe failure states; nine dashboard scenarios;
  clean-source RC gate, V2 identity and dirty/staged/untracked rejection tests.
- [Governance actions](repository-governance-actions.md): current main protection
  readback is false; no settings changed. External signing/publication/upload remain
  separate from engineering.

## Actual local validation so far

Logs are in `.tmp/final-hardening-v4/` pending final canonical evidence consolidation.
No historical V3 result is silently counted as a new V4 measurement.

| Check | Actual outcome | Log / scope |
| --- | --- | --- |
| Agent after model egress | 91 passed, 34.099 s | `agent-a-regression.log`; includes 12 new HTTP egress controls |
| Agent after dynamic plan | 100 passed, 36.643 s | `agent-b-final.log`; includes actual SIQ one/two/three-Skill cases |
| Model schemas | 10 passed | `pytest -q apps/control-api/app/tests/test_hackathon_model_contracts.py`; V1 retained, V2 added |
| Complete Control API | 650 passed, 15.29 s | `control-tests.log`; one existing Starlette deprecation warning |
| Web | 11 tests passed; normal and local builds passed | `web-tests.log`, `web-build.log`, `web-local-build.log`, locked npm install |
| AgentShield | go test, go test -race, go vet passed | `go-tests.log`, `go-race.log`, `go-vet.log`; Go 1.26.6 |
| Package / evidence tests | 12 passed | includes clean-source rejection, source identity, signed trifecta evidence checks |
| Browser first V4 checkpoint | nine scenarios passed | `browser-evidence/result.json`; fixture model, actual SIQ/tools, selected Skills, mobile, cookie and pairing checks |
| govulncheck | No vulnerabilities found | `govulncheck.log` |
| dependency audits | npm: zero vulnerabilities; pip-audit: no known vulnerabilities | `npm-audit.log`, `pip-audit.log`; local project itself is not a PyPI dependency |

The initial dynamic-plan run had two test-fixture representation failures (tuple
versus strict JSON list); the raw test input now passes through canonical JSON and
the complete 100-test rerun passes. The first browser command used an environment
without Playwright; the already installed system Python Playwright environment
ran the nine cases successfully. These failures remain in local logs.

A whole-working-directory secret scan also examined ignored runtime state and
caches, finding 37 entries there. It is not a publishable-source scan. The source
scan uses the exact tracked plus intended untracked source set and excludes ignored
runtime state. Do not put service.json tokens, pairing logs or state directories
in evidence or packages; public scan records contain redacted counts/categories.

## Completed real-provider and repository checks

The [canonical index](evidence/INDEX.md) links raw V4 records. Agent final replay:
100/100 (35.904 s); final browser replay: 9/9 without page errors, including actual
routing-value comparison. Fifty-five additional repository/adapter checks passed;
a disposable PostgreSQL database migrated to head successfully. Source-only
calibrated gitleaks found zero leaks.

Independent latest cohorts: StepFun planning + Ornith analysis 5/5; all-Ornith 5/5.
The first cohort for each was 4/5: the model chose an MCP candidate and SIQ refused
it. Those failures are retained, not hidden by the improved trusted-directory
prompt. Real PUBLIC and CONFIDENTIAL research-only runs verified local input
receipt and absence of the canary from remote requests. No silent fallback.

Fixed Agent controls: 23/23 expected, benign 5/5, unsafe actions 0/13,
provenance attacks blocked 8/8. Cohort task P50/P95/P99 (ms): mixed StepFun
7212.76/11391.61/11391.61; Ornith 5375.67/8331.98/8331.98. Sample counts are five
per cohort; these distributions are not an SLA or semantic-quality estimate.

## Final engineering acceptance

Frozen source `4da9e9e0a04c56620d101a583307b299b8484372` passed both actual PR workflows (30 mandatory jobs).
Clean RC build, extracted actual-model launch and the 170.00-second
real browser recording passed. The recording race in the first attempt was fixed,
revalidated and subjected to fresh CI/build; earlier artifacts and failures remain.

All 59 engineering tasks are complete. Four external/manual items remain:
main protection, official signing, public release and competition video upload.
PR #5 is open to V3 and unmerged. See the [final report](final-hardening-report.md)
for exact source, run IDs, artifact hashes, video and remaining risk boundaries.
