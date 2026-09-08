# Dataset card: fixed Agent security controls

Canonical corpus: [benchmarks/hackathon/cases.json](../../benchmarks/hackathon/cases.json), validated against its adjacent schema. It contains 23 authored, controlled tasks: five benign tasks and negative/task-effect scenarios. Thirteen tasks register an unsafe target; eight cover provenance. These populations overlap and must not be added as disjoint samples. Fixtures and executable examples are Apache-2.0 project material; third-party software and model responses retain their own terms.

Sources: synthetic repository files, example contacts such as `alice@company.example`, controlled MCP candidates and a local receiver. Attack proposals in the control cohort are deterministic fixtures, not measured model jailbreaks. The two historical five-task model cohorts are separate benign-utility samples with provider identity and failures preserved in the competition report. No new human-subject dataset is claimed.

The corpus was developed alongside the implementation and is not a held-out evaluation. Public examples can contaminate future model evaluation. Repeated runs reuse tasks, not independent task populations. Do not silently edit cases while reusing an existing corpus digest or denominator. New cases require a new version and a separate pilot/held-out protocol.

Public reports contain sanitized synthetic inputs, decisions, receipt chains, effect evidence and summary metrics. Private daemon state, signing seeds, authentication/pairing tokens and provider configuration are excluded. A public key supplied in the same report supports consistency verification, not external publisher trust. See [export policy](data-export-policy.md).
