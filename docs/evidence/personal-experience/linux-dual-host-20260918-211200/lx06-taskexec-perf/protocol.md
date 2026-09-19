# OpenShell task execution performance: LX06 current candidate

Schema: `openshell-taskexec-perf-protocol/v1`. This document is frozen before samples; its SHA256 is passed to the driver. Any changed method or budget requires a new run and retained old evidence.

- Candidate: unsigned Linux arm64 `70df54555205ccd6dca9779c5c18a4ccb2b5e1256038db387ff3030d572db02e`; source binding `036df1bd5fdd90d9ecb49f40d3f76761b1b85a03e74843c078600a0bacf77fab` (931 Go/mod/embed files).
- Baseline: `main@2187fea621ff40b368f2e01e51d26672239c9f8d` has task execution routes, but this task-execution protocol does not measure its binary. Relative values for S1–S4 are **not_measured**, never “not_comparable” solely because an older 9b8c09a baseline lacked a route. The separate B2 doctor protocol may provide a measured old/new comparison; do not merge its samples with this scope.
- Backend: OpenShell CLI 0.0.83, existing gateway `https://127.0.0.1:17671`, one uniquely named batch-owned sandbox. The gateway and other sandboxes are unchanged. Only this candidate's production `POST /v1/openshell/task-executions` route establishes the execution sample.
- Concurrency: one request at a time, no concurrent build, test, benchmark or independent performance run. Record host load and all attempts. The pending retention-expiry verifier spends this interval sleeping with its daemon down; if it starts during a timed round, record interference and stop rather than drop a sample.

## Frozen scenarios, order and budget

Three rounds, two untimed warmups per round/scenario. S1/S3/S4 have 15 measured samples per round; S2 has five. In rounds 1 and 3, order is S2 → untimed readiness conditioning → S1 → S3 → S4. Round 2 is S2 → conditioning → S3 → S1 → S4. Conditioning polls sandbox exec for at most 420 seconds after policy load and is recorded separately.

| Scenario | Timed operation | p95 ≤ | max ≤ |
| --- | --- | ---: | ---: |
| S1 | Product doctor policy readback through real CLI/gateway | 15000 ms | 30000 ms |
| S2 | Identical policy content set with `--wait` load confirmation | 60000 ms | 60000 ms |
| S3 | Approved bounded read-only command through product task executor | 2000 ms | 15000 ms |
| S4 | Product projection read for the persisted task execution | 1500 ms | 15000 ms |

The budgets and sequence are inherited unchanged from the frozen v1 [task-execution protocol](../../v6-f05-20260917-171950/protocol.md). Percentiles use nearest rank `ceil(p*n/100)` over every measured sample. Warmups alone are excluded by the prespecified rule. A refusal, HTTP mismatch, timeout, CLI stall, source drift, or competing benchmark makes the current run invalid; retain the failure and samples, stop, and do not select a better retry. Report absolute verdicts separately from the unmeasured relative comparison. Product behavior and gateway enforcement remain separate claims from latency.
