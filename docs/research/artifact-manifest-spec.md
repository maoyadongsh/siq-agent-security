# Research artifact identity

Reuse the existing package's `source-info.json`, `candidate-manifest.json`, `skill-inventory.json`, scoped SBOM and checksum verification. Do not build a second experiment engine or redefine receipt signatures.

A research release must additionally identify runtime source SHA, research documentation SHA, corpus SHA256, runner/verifier paths and SHA256, toolchain versions, build platform, native-tested platforms, build-tool SHA256, attempt/report digests, license-scope digest, citation-file digest and actual signing/attestation status. Different runtime and packaging-tool identities must remain distinct, as in V5.

The inner manifest records member digests but not its own digest or the enclosing archive digest. The external checksum records the finished archive's digest. Optional signing or GitHub build attestations authenticate only their stated subject and identity; hashing alone is not signing. No publisher seed is configured for the new research release, so any candidate must explicitly state unsigned until real publisher authentication is performed.

Never reuse `v0.3.0-rc.1` identity for changed research contents. Rebuild a new research candidate from a clean finalized SHA and attach its license/attribution package. No research version/tag is assigned merely by creating this specification.
