# Final submission checklist — V5

Only [final-submission-state.md](final-submission-state.md) defines current truth. Checks cover the documented scope, not production certification.

- [x] GitHub main source selected and frozen at `d1277116e8291e72b09b0462a19d0268b68bf46c` (protection is external_manual).
- [x] submission SHA recorded and equal to observed main HEAD.
- [x] Commit verified by GitHub.
- [x] ci green on submission SHA.
- [x] runtime-security green on submission SHA.
- [x] DGX hardware, inference and extracted candidate verified_for_scope.
- [x] StepFun actual planning verified_for_scope.
- [x] Agent Skills research / report / delivery E2E verified_for_scope.
- [x] Security demo, approval and negative paths verified_for_scope.
- [x] EffectEvidence and Completion verified_for_scope.
- [x] Controlled benchmark archived; earlier failures retained.
- [x] Video final, hash/decode/runtime equivalence rechecked; original source identity retained.
- [x] GitHub URL correct.
- [x] Demo instructions checked through clean candidate launch and browser pairing.
- [x] Fresh clean RC and inner/outer checksums correct.
- [x] Final evidence and submission packaging prepared.
- [ ] Competition form submitted — external_manual; no submission receipt available.
- [ ] Video uploaded — external_manual; no upload receipt available.
- [ ] GitHub prerelease published — external_manual; no publisher authorization.
- [ ] Publisher signing — unavailable; official key must be supplied through the supported mechanism.
- [ ] Main protection enabled and read back — external_manual.

Before external submission, compare remote main with the frozen SHA and verify the submission package checksums. A changed runtime or broken submission reopens the freeze; feature requests do not.
