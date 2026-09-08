# First research release scope

First candidate: `research-v0.1.0-rc.1`, a **source-only, unsigned research prerelease**. It contains the exact clean integrated Git source, retained vendored assets/notices, license/citation files, existing evidence and reproduction instructions. It does not contain newly compiled binaries, Python wheels, model weights, private state or separately recorded video. Existing historical generated UI assets in Git remain source-distribution members and keep their third-party notices.

The source archive is created by `scripts/research/package_source.py`, reusing the existing clean-source and SHA checks. It checks audited bundle/patch/lockfile identities, requires all referenced notices, extracts and scans the archive, and emits external SOURCE-INFO.json plus SHA256SUMS. These external files avoid self-referential archive hashes. They are not a cryptographic publisher signature or a binary SBOM. The complete source-file map and source/dependency inventories describe this payload.

Use the final main SHA only after the research PR's applicable CI succeeds and integration is verified. A later evidence-only commit does not retroactively change the candidate SHA. Do not reuse or overwrite the V5 `v0.3.0-rc.1` archive or any existing tag. Source-only scope does not fulfill future binary-native testing, independent reproduction, DOI/archive or model-budget milestones.

Future binary research candidates use the existing binary packager with a separately reviewed actual-payload SBOM, embedded notices and clean-launch acceptance. Those requirements remain tracked rather than misrepresented as completed by this source archive.
