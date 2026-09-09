# Release authentication

The original 2026-09-08 source publication was unsigned. No real publisher seed was configured, so its immutable `SOURCE-INFO.json` records `official_signature=false`. Historical evidence describes that original event, not subsequent detached signatures.

## Repository-identity release signing

The owner authorized digital signing on 2026-09-09. The [release-signing workflow](../../.github/workflows/release-signing.yml) uses Cosign v3.1.3 and GitHub Actions OIDC to sign the existing `SHA256SUMS` with a short-lived Sigstore certificate. No long-lived publisher private key or repository signing secret is required. The certificate binds the signature to this repository's workflow on `main`; Sigstore records public signing evidence in its transparency log.

Status: workflow prepared; do not describe the release as signed until the bundle has been published and freshly verified.

The detached `SHA256SUMS.sigstore.json` bundle contains the signature, certificate and transparency evidence. The signed checksum manifest authenticates both the named source archive and `SOURCE-INFO.json`. It does not cover GitHub's automatically generated ZIP/tar downloads, other tags, or arbitrary added assets. This is a post-publication signature over existing bytes, not a claim that the signing job originally built the archive. No GitHub artifact build-provenance attestation is claimed.

The original tag, archive, metadata and checksum bytes remain unchanged. In particular, the old `official_signature=false` field remains an accurate record of packaging time and of the absence of the historical Skill publisher-key signature. Current detached signing status is recorded separately. The existing v0.2.0 Skill signature covers only its own stated subject.

## Verify a downloaded release

Install [Cosign](https://docs.sigstore.dev/cosign/system_config/installation/) (the workflow is tested with v3.1.3) and GitHub CLI. Download into a new directory:

```bash
mkdir siq-release-verify
cd siq-release-verify
gh release download research-v0.1.0-rc.1 --repo maoyadongsh/siq-agent-security \
  --pattern SHA256SUMS --pattern SHA256SUMS.sigstore.json \
  --pattern SOURCE-INFO.json --pattern siq-agent-security-research-v0.1.0-rc.1.tar.gz
cosign verify-blob --bundle SHA256SUMS.sigstore.json \
  --certificate-identity 'https://github.com/maoyadongsh/siq-agent-security/.github/workflows/release-signing.yml@refs/heads/main' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
  SHA256SUMS
# Proceed only after signature verification succeeds.
sha256sum --check --strict SHA256SUMS
```

Require both commands to succeed. Pin the exact certificate identity and issuer above; never replace them with a permissive wildcard or disable transparency-log verification. A checksum alone authenticates no publisher. A valid signature establishes repository workflow identity, not legal ownership, code safety or scientific validity.

## Maintainer operation

Run `gh workflow run release-signing.yml --ref main -f tag=research-v0.1.0-rc.1` after this workflow is integrated. Only the canonical repository on `main` can run the signing job. It verifies the tag's resolved source commit and all original asset sizes and hashes against the reviewed [publication record](evidence/github-research-release.json) before signing. It rejects substituted archives/metadata, modified checksum lists, unknown tags and moved tags. The signing job executes no code from the downloaded archive.

The workflow verifies the signature, tests rejection of tampered bytes and a wrong signer, uploads only the new signature bundle without `--clobber`, then downloads and verifies the published files again. If a rerun reports an existing bundle, inspect and verify that bundle; do not delete or overwrite it to hide the previous signing event. Additional releases require their own reviewed publication record and an explicit update of the workflow's record selection. This prevents signing arbitrary unreviewed release assets.

Receipt-chain verification proves internal experiment consistency under the recorded keys, separately from release provenance and separately from whether an experiment supports a scientific conclusion. A signed release would not enlarge same-UID isolation, observer scope or statistical claims.
