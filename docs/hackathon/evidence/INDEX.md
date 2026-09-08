# Hackathon evidence

V4 local engineering evidence, 2026-09-08. Each record retains its actual source
SHA/file hashes, provider and sample scope. Final RC, PR CI and video acceptance
are tracked in the [V4 progress report](../final-hardening-progress-v4.md).

## 1. Agent Skills

[Actual selected 1/2/3-Skill browser cases](final-hardening-v4/browser-v3/result.json)
and [real-model research-only runs](final-hardening-v4/locality.json) show the
Agent selecting and executing registered Skills. The browser control uses an
explicit FixtureProvider; the locality runs use StepFun planning and Ornith analysis.

## 2. NVIDIA DGX Spark

[Actual hardware and runtime preflight](final-hardening-v4/dgx-preflight.json),
[local inference / confidential transport proof](final-hardening-v4/locality.json)
and [measured runtime component samples](final-hardening-v4/runtime-performance.json).
Model listing, hardware identity and actual inference are separate evidence.

## 3. StepFun

[Latest StepFun-planning cohort](final-hardening-v4/stepfun-cohort-v2.json),
[receipt/effect verification](final-hardening-v4/stepfun-verification-v2.json),
[earlier 4/5 cohort retained](final-hardening-v4/stepfun-cohort.json).
Actual call metadata separates remote StepFun planning from local Ornith analysis
and recipient reasoning; no fixture or fallback is labeled StepFun.

## 4. Security

[23 fixed Agent controls](final-hardening-v4/control-cohort.json),
[independent receipt/effect verification](final-hardening-v4/control-verification.json),
[nine browser scenarios](final-hardening-v4/browser-v3/result.json),
[local regression checks](final-hardening-v4/validation.json).
Controls cover MCP injection, provenance, stateful trifecta and approval; fixture
proposals measure the runtime boundary, not real-model attack susceptibility.

## 5. Effect & Completion

[Actual missing/conflicting/verified effects](final-hardening-v4/control-cohort.json)
and [visible completion outcomes](final-hardening-v4/browser-v3/result.json).
Research-only remains `researched` with no claimed external effect; SIQ's UNKNOWN
effect status is preserved. File and controlled receiver proofs do not establish
universal SaaS outcomes or OS isolation.
