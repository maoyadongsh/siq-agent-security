# DGX Spark performance evidence — 2026-09-08

Current primary is StepFun. Its [latest separate cohort](evidence/dgx-spark/performance-step-plan-low-20260908.json)
has 5/5 task completion: planning P50/P95/P99 4.270/5.638/5.638 seconds;
15 model calls 5.638/19.320/19.320 seconds; five complete tasks
15.683/33.562/33.562 seconds. Earlier ornith measurements below remain separate
historical populations, not StepFun performance evidence.

The later [direct-output ornith projection](evidence/dgx-spark/performance-direct-corrected-20260908.json)
uses a separate five-task cohort: 5/5 completion, 15 accepted model calls,
model-call P50/P95/P99 **1.510/6.532/6.532 seconds**, and task-attempt
P50/P95/P99 **5.574/9.813/9.813 seconds**. It retains the original component
samples as a distinct population. This small local sample is not an SLA or
semantic-quality result. The initial `performance-direct-20260908.json`
projection had a stale generic limitation mentioning a failed planning task;
the corrected projection uses the same input hashes and measurements with
population-appropriate wording. Raw task captures are unchanged.

The earlier JSON-object cohort and its failure remain described below.

The local host is NVIDIA DGX Spark / GB10 / aarch64, driver 580.126.09. Hardware
and service identity are recorded in the [environment evidence](evidence/dgx-spark/ornith-environment-20260908.json).
The driver/device were also read again with `nvidia-smi` during this measurement.
StepFun was deferred at the time of that earlier capture; its model samples identify
`Ornith-1.5-35B-A3B-NVFP4`.

The table reports measured nearest-rank percentiles. **Model/Agent samples and
SIQ component samples are different populations and code snapshots.** Do not
add their percentiles or interpret the component figures as total Agent latency.

| Measurement | Samples | P50 | P95 | P99 |
| --- | ---: | ---: | ---: | ---: |
| Ornith call, including transport and strict validation | 13 | 8.086 s | 35.497 s | 35.497 s |
| Model planning call | 5 | 8.504 s | 9.024 s | 9.024 s |
| Complete Agent task attempt | 5 | 20.273 s | 47.042 s | 47.042 s |
| Completed Agent tasks only | 4 | 20.273 s | 47.042 s | 47.042 s |
| SIQ Engine.Decide | 100 | 8.230 ms | 12.178 ms | 13.225 ms |
| SIQ provenance resolution | 100 | 0.244 ms | 0.312 ms | 0.400 ms |
| SIQ context validation | 100 | 0.123 ms | 0.152 ms | 0.171 ms |
| Receipt append/fsync | 100 | 7.550 ms | 11.353 ms | 12.444 ms |
| Effect SubmitFile processing | 100 | 5.877 ms | 6.344 ms | 6.673 ms |

The five Agent attempts are the archived utility cohort: **4/5 complete**;
one planning call fails `contract_fields_invalid`. All-attempt latency includes
that failure and all 13 model calls; completed-only latency excludes the failed
task explicitly. No warm-up or failed call was silently discarded from this
model cohort. A small five-task sample does not support an SLA, stable model
throughput estimate, concurrent-load claim or inference-quality conclusion.

The component measurements reuse the existing runtime-security performance
runner and Go stage tests: five warm-up iterations followed by 100 sequential
samples per fixture. Decide uses actual signed Intent V3, context/provenance,
deployed test Grant and persistent receipts; it excludes HTTP, model and tool
execution. The effect fixture measures SubmitFile with a synthetic authorized
action and real signing/publication; it excludes file capture and receiver
latency. No race instrumentation was used for these timing samples.

Files and reproducibility:

- [Raw component samples and source hashes](evidence/dgx-spark/runtime-performance-20260908.json).
- [Raw real-model Agent cohort](evidence/benchmark-20260908/ornith-fixed.json).
- [Combined measurements, input hashes and limitations](evidence/dgx-spark/performance-summary-20260908.json).

```bash
GOTOOLCHAIN=go1.26.6 python3 benchmarks/runtime-security/performance.py \
  --out .tmp/new-runtime-performance.json
apps/control-api/.venv/bin/python scripts/hackathon/performance-report.py \
  --model-report docs/hackathon/evidence/benchmark-20260908/ornith-fixed.json \
  --stage-report .tmp/new-runtime-performance.json \
  --out .tmp/new-hackathon-performance.json
```

The aggregation command verifies the Agent cohort's existing SIQ receipt/effect
evidence, recomputes the component percentiles from raw samples and records input
hashes. It does not claim cryptographic attestation of clock readings or GPU
measurements. These results complete the scoped local performance report, not
final competition deployment or release acceptance.
