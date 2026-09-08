# Prerelease publication preparation

[Release notes](release-notes-v0.3.0-rc.1.md) are prepared separately so that operational commands are not published as release notes.

## Prepared commands — publication remains external_manual

Do not execute these until publisher authorization is explicit. Recheck remote main and tags first. Never overwrite an existing tag; if either rc.1 tag spelling exists, prepare a fresh rc.2 build and its metadata instead.

```bash
env -u GITHUB_TOKEN git fetch --all --prune
test "$(git rev-parse origin/main)" = "d1277116e8291e72b09b0462a19d0268b68bf46c"
test -z "$(git tag -l 'siq-agent-security-v0.3.0-rc.1' 'v0.3.0-rc.1')"
# Local tag preparation, only after publisher authorization:
git tag -a siq-agent-security-v0.3.0-rc.1 d1277116e8291e72b09b0462a19d0268b68bf46c -m 'Hackathon prerelease candidate'
# No publisher signature is implied by an annotated tag.
env -u GITHUB_TOKEN git push origin refs/tags/siq-agent-security-v0.3.0-rc.1
env -u GITHUB_TOKEN gh release create siq-agent-security-v0.3.0-rc.1   --verify-tag --prerelease --title 'SIQ Agent Security v0.3.0-rc.1 — Hackathon candidate'   --notes-file docs/hackathon/release-notes-v0.3.0-rc.1.md   .tmp/final-release-v5/rc/siq-agent-security-v0.3.0-rc.1.tar.gz   .tmp/final-release-v5/rc/siq-agent-security-v0.3.0-rc.1.tar.gz.SHA256SUMS
```

No commands in this publication block were executed. Official signing requires the existing publisher mechanism and real key; do not use a test, development or temporary key.
