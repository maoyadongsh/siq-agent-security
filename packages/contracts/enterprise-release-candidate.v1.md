# Enterprise release candidate v1

ENT-004 development preparation, not an installer or publisher authorization.
`scripts/release/enterprise_candidate.py` exports a full commit ID using Git,
requires the exported allowlisted source inventory to match an independently
reviewed `siq-release-source-inventory/v1` inventory, and builds offline with the
local Go toolchain. Working-tree modifications and untracked files are excluded.
The inventory covers Edge, Hermes/OpenClaw/directory source and license files;
it is not the personal-client release inventory.

Linux amd64 and arm64 output follows enterprise-release/v1 artifact paths.
Default connectors are hermes, openclaw and directory; repeated `--connector`
selects a subset. Version is injected into Edge and Connector version variables.
Old source without version injection support is rejected. Builds use readonly
modules, no workspace, no toolchain downloads and no cgo; missing cached
dependencies fail rather than being fetched. ELF class/endianness/machine,
artifact size and digest are checked without executing candidate binaries.

`CANDIDATE.json` uses `enterprise-release-candidate/v1`, includes product,
version, source_commit, artifacts, exported source_inventory, packaging tool
and shared packaging helper digests and Go version. `signed`, `installable`, `published` are always false;
native_installation_acceptance is `not_run`. `SHA256SUMS` is descriptive only.
There is deliberately no release.json, signature, embedded signing key or READY.
The production installer must continue rejecting this candidate.

The output also contains a `siq-agent-security-enterprise-VERSION-unsigned-candidate.zip`
with a same-named root directory. It contains the binaries, candidate metadata,
review instructions and licenses, not itself or the outer SHA256SUMS. ZIP names,
contents and executable bits are verified; entry timestamps are fixed for repeat
build comparisons. Outer SHA256SUMS covers all loose files and the ZIP, excluding
itself. Neither hash list nor ZIP establishes publisher trust. Review without
executing binaries; copying an old release.json into the directory is forbidden.

`publisher-signing-input.json` contains the exact compact sorted-key ASCII JSON
bytes of enterprise-release/v1 excluding signature, including the original
publisher's public key. It contains no newline, seed, private key, placeholder
signature or install authorization. The request pins the reviewed source commit,
version and artifact hashes. It is included in the portable archive/checksums.
An authorized external publisher may sign these exact bytes with Ed25519, but
the resulting envelope must still be checked by the independent compiled trust
root and artifact verifier. The input file itself must not be renamed release.json.
Candidate construction neither invokes a signer nor authorizes publication.

Output must be a new directory outside the checkout. Builds happen in a private
temporary directory; output creation is exclusive. Transfer failure may leave
an incomplete candidate for manual inspection, never an installable release.
Stable output-parent ownership and trusted reviewed source/toolchain are required;
this is not a sandbox against malicious compiler/source or same-user tampering.

Example (replace placeholders with a reviewed full commit and inventory):

```text
python3 scripts/release/enterprise_candidate.py \
  --source-sha REVIEWED_40_HEX_COMMIT \
  --expected-source-inventory /path/to/reviewed-enterprise-source.json \
  --version 0.1.0-rc.1 --out-dir /tmp/new-enterprise-candidate
```

Signing with the original publisher identity, download distribution, actual
device installation, registration and service lifecycle acceptance are separate
pending gates. Cross compilation or a candidate checksum does not satisfy them.
