# Session digest scanner calibration

PR #83's prior CI checkout was merge `4c7a29574e88b99fb75603dd5fda82a7c801ec82`
over implementation head `72140795963244d293232c905a34ef00312b8253`.
The unmodified rule produced 12 matches in head history plus six matches in
the synthetic merge diff, accounting for all 18 reported CI findings. They
refer to the same six locations in the same evidence JSON blob. The frozen
generator, original evidence, and manifest hashes identify a content digest
of isolated native session routing metadata; no credential value is excepted.

The new generic-api-key exception requires the exact repository-relative
evidence path, exact field line, and one reviewed digest. It does not allow
new hashes, other fields, other paths, or a prefixed copy of the same path.
Default scanner rules and all previous calibration assertions remain enabled.
The first reviewed draft accepted a path suffix; the new negative fixture
rejects that draft with exit 1. The exact-path rule passes the calibration
with exit 0. The actual fixed CI merge's complete reachable history, including
merge diffs, then scans with exit 0 and zero findings under Gitleaks 8.24.2.

`verification.json` records the scanner/config/calibration digests, commands,
actual exits, and timings. `finding-classification.json` contains only selected
non-secret provenance and finding locations. `provenance.json` records hashes
of retained local originals. Workspace paths in published commands are replaced
with placeholders; no session identifier or raw private state is published.

These are local checks against the specified historical merge using the
development rule files. They do not claim that later commits or the final PR
head have passed CI, and do not increase the Windows native acceptance count.
No history rewrite, credential rotation claim, product-policy change, or broad
secret-pattern suppression was performed.
