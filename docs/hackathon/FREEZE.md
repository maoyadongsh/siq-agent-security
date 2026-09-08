# Competition freeze — V5

Date: 2026-09-08T13:53:33.515628+00:00.

- Submission SHA: `d1277116e8291e72b09b0462a19d0268b68bf46c` = observed main HEAD.
- RC: `siq-agent-security-v0.3.0-rc.1`, fresh clean source; four cross-builds; native linux-arm64 smoke passed.
- RC SHA256: `205957fbba10b1019d826232cd004c19ec2444d1519a70bd03137375075369a1`.
- CI: ci `34230055303`, runtime-security `34230055283`, both success on submission SHA.
- DGX: NVIDIA DGX Spark / GB10; actual local Ornith inference and extracted RC verified_for_scope.
- StepFun: actual remote planning verified_for_scope; confidential canary absent from transport; local-failure remote calls = 0.
- Video: existing narrated MP4 retained, hash/decode/runtime equivalence verified_for_scope; no new recording.
- Evidence manifest: [evidence-manifest.json](evidence/evidence-manifest.json).
- Current truth: [final-submission-state.md](final-submission-state.md).
- Final report: [final-release-report.md](final-release-report.md).
- Submission package: `.tmp/final-release-v5/submission/`; external manifest binds the final V5 documentation commit after commit creation.

**STOP DEVELOPMENT.** Only a P0 correctness bug, P0 security bug or broken competition submission can reopen code changes. New features, refactors, performance ideas, papers and architectures go to [POST-HACKATHON.md](POST-HACKATHON.md).

This freezes the selected source and local artifacts; GitHub branch protection, official signing/publication, competition form and video upload remain explicit external actions. No claim of enforced branch protection or external submission is made.
