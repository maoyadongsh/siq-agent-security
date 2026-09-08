# Competition evidence — six entries

Identity and status: [sole current submission state](../final-submission-state.md).
The [manifest](evidence-manifest.json) binds the submission SHA to canonical files, preserving each historical record's actual source and scope.

## 1. Agent Skills

[Research / report / delivery browser cases](final-release-v5/browser/result.json), [four-Skill static verification](final-release-v5/skill-verification.json), and [actual-model RC task](final-release-v5/rc-checkpoint.json). Nine browser controls use the explicitly labelled FixtureProvider; the RC task uses StepFun and Ornith.

## 2. NVIDIA DGX Spark

[Hardware, OS, GPU, driver, CUDA and model listing](final-release-v5/dgx-preflight.json), [actual canary inference and transport digests](final-release-v5/locality.json), and [local transport failure with zero remote calls](final-release-v5/local-failure.json). [Canonical measured performance report](../dgx-performance-report.md) retains its historical sample identity.

## 3. StepFun

[Actual StepFun planning in the extracted RC](final-release-v5/rc-checkpoint.json), [transport and locality](final-release-v5/locality.json), [latest retained 5/5 cohort](final-hardening-v4/stepfun-cohort-v2.json) and [its independent verification](final-hardening-v4/stepfun-verification-v2.json). [Earlier 4/5 failures retained](final-hardening-v4/stepfun-cohort.json).

## 4. Runtime Security

[23 fresh fixed controls](final-release-v5/control-cohort.json), [signed evidence verification](final-release-v5/control-verification.json), [68 clean-main regression commands/results](final-release-v5/regression/checks.json), and [nine dashboard scenarios](final-release-v5/browser/result.json). MCP proposals use real SIQ provenance decisions; fixture controls do not measure model attack susceptibility.

## 5. Effect & Completion

[Actual missing/conflicting/verified effects and receipts](final-release-v5/control-cohort.json), [independent envelope verification](final-release-v5/control-verification.json), and [candidate normal Completion](final-release-v5/rc-checkpoint.json). Tool success plus absent receiver evidence remains INCOMPLETE. Research-only makes no file/delivery-effect claim. The receiver is controlled, not universal SaaS proof.

## 6. Reproducibility / Release

[Clean RC, source identity and artifact hashes](final-release-v5/rc.json), [main/PR/CI observations](final-release-v5/repository.json), [final engineering report](../final-release-report.md), [final checklist](../FINAL-SUBMISSION-CHECKLIST.md), and [retained video freeze](final-release-v5/video-freeze.json).

[Original narrated video metadata/subtitles](final-hardening-v4/narrated-video-zh.json) and [recording task IDs](final-hardening-v4/video.json) retain the original source. The [benchmark report](../benchmark-report.md) and [V4 report](../final-hardening-report.md) preserve historical evidence and failures. [Original V4 manifest](evidence-manifest-v4.json) is archived unchanged. The RC is unsigned and unpublished; external submission/governance status is explicit in current truth.
