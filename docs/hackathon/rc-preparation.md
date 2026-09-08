# Local RC preparation contract

The candidate is a local, unpublished `0.3.0-rc.1` preparation artifact. Its
baseline SHA and exact dirty source-file hashes must be recorded; a dirty tree
must not be represented as an immutable final Git commit. The package retains
the runtime's repository layout, including proposal schemas and the three Skills.

Build from the copied source snapshot, with Go 1.26.6, into separate Linux
amd64/arm64, macOS arm64 and Windows amd64 binaries. The embedded local Web UI
must be present. The runnable competition service is Linux-only because its
managed process identity uses `/proc`; cross-compiled daemon binaries do not
prove competition-service operation on macOS or Windows.

Include source provenance, SHA256/size inventory, a scoped CycloneDX component
inventory, the existing signed security-Skill manifest as historical material,
an explicitly unsigned candidate Skill/content inventory, quick start and
evidence summary. Do not change the historical release pins, invent an official
signature, generate a replacement release trust root, or publish a release.
Official signing and final-commit/repository governance remain separate gates.

The launcher must use packaged Python code, fixtures, schemas and prebuilt
binary with a new external private state directory. It must validate the file
inventory before launch and expose the existing loopback service, not another
Web application. A package checkpoint must exercise actual primary StepFun and the
existing SIQ/effect pipeline from the copied package.

Before archiving, audit the package for private state, symlinks and unexpected
files, and run an effective secret scanner. A scan with an empty rule set is
not valid evidence. The earlier source-snapshot scan is superseded: inspection
found `.gitleaks.toml` lacked `extend.useDefault=true`, leaving no configured
rules in Gitleaks 8.24.2. The configuration is corrected and must be calibrated
with a synthetic token negative before its results are used for acceptance.

## Candidate 1 checkpoint

The [preparation record](evidence/rc-candidate1-preparation-20260908.json) identifies
a local archive containing the exact source snapshot, four actual cross-built
binaries, source/Skill inventories, checksums, quick start and a CycloneDX 1.5
component inventory validated against the official schema. The builder runs real
scanner calibration and scans the candidate before archiving. Five package tests
reject tampering, added/removed files, symlinks, executable mode changes, unsafe
state placement and false official-signature claims.

The archive was extracted into a separate directory. Its actual launcher
started a new Linux arm64 service, and a [real StepFun task](evidence/rc-candidate1-launch-20260908.json)
completed with 26 verified receipts and two verified effect envelopes in 48.17
seconds. A second inventory check confirmed no package files changed during
execution. State and pairing credentials stayed outside the package. This proves
the recorded Linux launch path, not native execution on other build targets.

Candidate 1 is local and unsigned. It predates a subsequent launcher lint-only
cleanup and documentation additions; a final candidate refresh remains required.
The historical test-token finding was classified and the calibrated history
rescan passed, as tracked in [repository regression](repository-regression.md). No history rewrite,
official signing, push or release was performed.

## Candidate 2 acceptance

The [refreshed candidate](evidence/rc-candidate2-preparation-20260908.json) includes
the complete stateful demo, seven-scenario Dashboard and current provider code.
Its 1,575-file inventory, four Go 1.26.6 target binaries, calibrated secret scan,
official-schema-validated scoped SBOM and four actual Skill admissions pass.
The [extracted-package StepFun task](evidence/rc-candidate2-launch-20260908.json)
completes with 26 verified receipts and two verified effect envelopes in 15.33
seconds. Package contents remain unchanged after actual launch and execution.

The [final report](final-engineering-report.md) is post-build acceptance material;
the frozen package source is exactly the inventory in its `source-info.json`.
This candidate remains unsigned and unpublished. Further documentation outside
that snapshot does not silently change the archive or its recorded checksum.
