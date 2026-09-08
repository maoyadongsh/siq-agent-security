# V4 frozen demonstration

Main story: review selected repository sources, create a report, deliver it to
Alice. Open the existing `/demo` page using [HACKATHON.md](../../HACKATHON.md).
StepFun plans from public metadata, Ornith analyzes locally on DGX, and SIQ
independently authorizes actions and evaluates observed effects.

| Time target | Actual interaction | Visible evidence |
| --- | --- | --- |
| 0:00–0:15 | Show task, source identity, provider and hardware card | Skills give agents capabilities. Who authorizes the consequences? |
| 0:15–0:40 | Real-model research-only | One selected Skill; actual local inference; no delivery claim |
| 0:40–1:20 | Real-model normal delivery | Three selected Skills; ALLOW; observed report and receiver; verified Completion |
| 1:20–1:50 | Explicit FixtureProvider attack controls | Actual trusted baseline followed by MCP attacker routing DENY |
| 1:50–2:15 | Same-value scenario | The actual same mailbox from trusted directory ALLOW and MCP DENY |
| 2:15–2:35 | Fake-success scenario | Actual reported success, absent receiver effect, incomplete Completion |
| 2:35–2:50 | Show limitations and evidence | Model proposes; SIQ authorizes; evidence determines completion |

The optional live approval act shows HOLD, exact parameters and expiry, operator
approval, SIQ recheck and execution. The nine-scenario browser regression also
covers research+report, conflicting effects and stateful trifecta. These extra
acts need not be squeezed into the 2–3 minute recording.

`scripts/hackathon/record-demo.py` records browser interactions against an exact
clean candidate with separate real-model and explicit test services. Captions
explain the evidence; they do not replace decisions or hide waiting. No playback
speed changes or success edits are permitted. A failed real-model attempt remains
a failed attempt. The script records source SHA, task IDs, providers, duration and
video hash outside Git. Final recording status is tracked in the
[V4 report](final-hardening-progress-v4.md); raw evidence has one entry:
[Evidence index](evidence/INDEX.md).
