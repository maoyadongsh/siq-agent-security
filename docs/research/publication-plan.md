# Source prerelease publication procedure

Authorization: the repository owner requested direct implementation of the research open-source plan and confirmed project ownership. Publish the distinct source prerelease after its concrete candidate passes checks. Do not overwrite existing tags or assets.

1. Verify the exact research PR head and required CI results. Integrate through the PR. Any sole-maintainer administrator exception is recorded with the successful checks.
2. Fetch final main into a clean detached worktree. Recheck source identity, applicable checks and absence of working-tree changes. Build `research-v0.1.0-rc.1` with scripts/research/package_source.py using the calibrated scanner.
3. Verify external SHA256SUMS and archive member/license identities. Record actual source SHA, archive and metadata digests, package kind and unsigned status. Keep private build state outside the candidate.
4. Create the GitHub prerelease at that exact SHA with the source archive, SOURCE-INFO.json and SHA256SUMS. Use these release notes, with actual CI/source references. Read back release metadata, download uploaded assets into a new directory and verify their checksums.
5. Record the real URL and readback in evidence; update task states only for fulfilled source-release scope. Do not fabricate DOI or external-reproduction success. Zenodo remains unavailable until an archival account is connected.
