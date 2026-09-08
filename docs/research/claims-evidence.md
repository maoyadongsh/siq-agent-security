# Claims and evidence

Machine-readable bindings and digests: [claims-evidence.json](claims-evidence.json). Original V5 identities are retained; new development runs are separate.

| Claim | Evidence | Scope |
| --- | --- | --- |
| V5 fixed controls: 23/23 expectations, benign 5/5, unsafe materialization 0/13, provenance 8/8 | [controls-v5](../../docs/hackathon/final-submission-state.md) | synthetic fixed controls; populations differ |
| Latest retained StepFun benign cohort: 5/5 | [model-stepfun](../../docs/hackathon/evidence/final-hardening-v4/stepfun-cohort-v2.json) | five benign tasks; not attack robustness |
| Latest retained Ornith benign cohort: 5/5 | [model-ornith](../../docs/hackathon/benchmark-report.md) | five benign tasks; original cohort identity retained |
| Earlier model utility failures remain visible (4/5) | [historical-failure](../../docs/hackathon/benchmark-report.md) | do not replace failed cohorts with later attempts |
| Same recipient value: trusted database allowed, MCP provenance denied | [same-value](../../docs/hackathon/evidence/INDEX.md) | configured source identities; not general semantic provenance |
| Fake reported success without receiver effect remains incomplete | [effects](../../docs/hackathon/evidence/INDEX.md) | controlled receiver and observer; not universal external delivery |
| V5 confidential canary excluded from remote HTTP bodies; local refusal fails closed | [locality](../../docs/hackathon/evidence/final-release-v5/locality.json) | operator classification and observed transports only |
| V5 local connection refusal produced zero StepFun transport calls | [local-failure](../../docs/hackathon/evidence/final-release-v5/local-failure.json) | single controlled failure path |
| Research development: 23/23, 318 receipts, 20 effect envelopes verified | [new-controls](../../docs/research/evidence/reproduction-b/verification.json) | dirty worktree run; not clean release acceptance |
| Research development: all nine fixture browser scenarios passed | [new-browser](../../docs/research/evidence/reproduction-a/browser.json) | Linux aarch64 CPU fixtures on DGX host; no new model inference |

Missing/unknown evidence is never converted to successful absence. Same-UID isolation, statistical guarantees, universal MCP security and general SaaS delivery proof are not claimed.
