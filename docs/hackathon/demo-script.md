# Five-minute demonstration

Before presenting, run the [quick start](../../HACKATHON.md), check service
health, and obtain a fresh pairing code with `scripts/hackathon/pair.sh`.
Check the visible provider label. Use StepFun for the normal task; ornith is the explicit backup. If using the
explicit test profile for deterministic attack demonstrations, say so aloud.
Never describe a forced fixture-model choice as real-model susceptibility.

| Time | Operator action | Explain and show |
| --- | --- | --- |
| 0:00–0:30 | Open `/demo`, pair, show the task and provider | “The model proposes a review and delivery. SIQ authorizes the actual actions.” |
| 0:30–1:30 | Submit normal delivery | Three Skills, committed Intent, allowed actions, actual report and receiver effect evidence; explain the observed scope |
| 1:30–2:30 | Run MCP attack and same-value provenance scenarios | Expand recipient provenance. Compare the trusted directory assertion with the SIQ-returned MCP assertion. Equal mailbox text does not grant authority |
| 2:30–3:20 | Run approval scenario and approve the displayed report verifier | Show HOLD, exact parameters and expiry, operator click, SIQ recheck and actual fixed process. The process result alone is only reported evidence |
| 3:20–4:10 | Run fake success | Tool says success; receiver has no observed delivery; Completion remains incomplete |
| 4:10–4:40 | Run stateful egress scenario | Allowed confidential fixture read → allowed web response → denied next request, in one session; three SIQ state snapshots, zero report or delivery |
| 4:40–5:00 | Show benchmark and limitations | 23/23 deterministic controls; latest StepFun and ornith 5/5 separate small utility cohorts; earlier failures retained; no universal security or review-quality claim |

These times are presentation targets, not guaranteed execution latency. Start
with configured StepFun (or explicitly selected warm local backup) and leave time for task completion. Approval expires
after about 60 seconds. A failed model call remains a failed attempt; show its
diagnostic and do not relabel it as an attack blocked by SIQ.

For reproducible recorded evidence, use the archived [seven-scenario browser
run](evidence/browser-trifecta-20260908/result.json),
[actual model cohorts](structured-model-output.md), and [live GitHub task](live-source-validation.md).
Archived screenshots are evidence of their labelled run, not a substitute for
claiming that the current live session ran successfully. No video has been recorded.
