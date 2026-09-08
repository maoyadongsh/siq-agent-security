# Research questions

These are candidate questions, not claims of accepted novelty.

| Question | Existing implementation/evidence | Additional research required |
| --- | --- | --- |
| RQ1: Can independent authorization constrain proposals while preserving benign completion? | Secure Agent and 23 fixed controls in benchmarks/hackathon | Held-out tasks, paired comparisons and uncertainty |
| RQ2: Does identical value with different provenance change authorization? | same-value control; trusted database vs MCP | More source types and unseen contexts |
| RQ3: Can completion distinguish reported success from observed effects? | fake-success/conflicting controls; runtime EffectEvidence | Observer faults and external effect systems |
| RQ4: Does configured locality keep confidential analysis out of remote transport? | V5 canary and connection-refusal checks | Independent environments and classification errors |
| RQ5: What utility/cost tradeoffs accompany dynamic 1/2/3 Skill execution? | research-only/report/delivery paths; small model cohorts | Preregistered cost decomposition and enough task units |

See [claims](claims-evidence.md). Repeated random seeds of one task are not independent task samples. Ablations must stay in disposable test fixtures and must not weaken a released authorization path.
