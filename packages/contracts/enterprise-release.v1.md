# Enterprise release v1

ENT-004 additive envelope; does not alter historical skill-manifest signatures.
The publisher uses the existing Ed25519 release identity. No runtime-generated
key, manifest-contained key or test key may establish production trust.

Exact fields: `schema_version` = `enterprise-release/v1`, `product` =
`siq-agent-security-enterprise`, `version`, `source_commit` (40 lowercase hex),
`artifacts`, `signed_by` (existing raw public key standard base64), `signature`
(64-byte lowercase hex). Version follows installation-plan version syntax.
Each artifact has exact fields `id` (`edge-agent` or existing Connector ID),
`os` (`linux`), `arch` (`arm64`/`amd64`), `path`, `sha256` (64 lowercase hex),
`bytes` (integer, 1..268435456). Path must equal `bin/{arch}/edge-agent` for Edge
or `bin/{arch}/{id}-connector`. Each architecture present needs exactly one Edge
and at least one Connector; identities/paths are unique. At most 26 artifacts.

Signature input is sorted-key compact ASCII JSON of the envelope excluding only
`signature`, using the existing Edge canonical JSON implementation (Python
`json.dumps(sort_keys=True,separators=(',',':'),ensure_ascii=True)`). Verify exact
structure before accepting signature. Reject duplicate/unknown/missing keys,
nulls, invalid UTF-8, oversized envelopes, unsupported platforms and paths.

Plan binding independently compares raw manifest SHA-256, version, selected
architecture and every selected Connector digest/version/protocol. Caller must
still validate plan origin/tenant/environment/expiry, confirm scope and verify
actual artifact bytes before executing. Parsing a signed manifest does not
register a device, approve business operations or verify installed files.

This contract and verifier do not constitute a signed release or publisher
authorization. Production signing/packaging and artifact staging remain pending.

Linux `edge-agent verify-enterprise-release --release FILE` exposes the compiled
publisher verifier without requiring a device or installation plan. The input is
bounded by MaxBytes and must be a regular non-symlink file. No key override,
network, state writes, artifact execution or installation. On success it emits
enterprise-release-verification/v1 with version, source_commit, raw manifest
SHA-256, publisher_signature_verified=true, artifact_bytes_verified=false and
installed=false. This proves only envelope verification; actual bytes and plan
binding still require the existing preparation/staging flow. Errors are fixed
and do not emit a partial success report. Non-Linux CLI remains unsupported.

Optional `--bundle ABSOLUTE_DIRECTORY` additionally calls VerifyReleaseBundle:
reverify the compiled publisher, then check every signed artifact through the
same descriptor/hash checks as installation preflight. Unlike plan-selected
VerifyBundle, this includes all architectures and connectors in the envelope.
Only after all pass is artifact_bytes_verified=true; installed remains false.
No arbitrary files outside the signed list are inspected or certified. This is
a point-in-time byte check, not a durable execution handle, source provenance
proof, license attestation or plan authorization. Installation still revalidates
plan scope and uses private staging. Missing/unsafe/tampered files emit no success.

Linux bundle preflight (`VerifyBundle`) verifies the signed plan-bound manifest,
then reads only selected architecture Edge and selected Connectors. Walk every
absolute bundle directory and artifact component with descriptor-relative
no-follow opens; reject symlinks, nonregular files, hard links, nonexecutable
files, group/world-writable files and set-ID bits. Hash an at-most-declared-size
plus one byte bounded stream and require exact size and digest. Never execute
bundle contents. Errors must not include paths or bytes.

This is a point-in-time preflight, not an execution handle or secure staging:
callers must copy into private staging and verify staged bytes before activation;
reopening the original path after this check is not protected against replacement.

Linux `StageBundle` revalidates publisher and plan binding, creates a random
0700 `stage-<32 hex>` child in an existing current-user-owned private directory,
and copies selected files with exclusive descriptor-relative creation. It hashes
the bytes being copied, syncs and changes executables to 0500, and preserves the
signed relative layout. Only after all files succeed does it persist and sync
`release.json`, then `READY` containing the raw manifest digest, and sync the
directories. The parent and its ancestry must be controlled/stable; same-user
or root tampering is outside this filesystem boundary.

On failure, return a fixed error and no activation path. Partial private stages
are retained for explicit recovery, never reused/activated automatically; no
existing installation is overwritten or deleted. READY is a completion marker,
not an authorization/signature: recovery must reverify contents and live plan
context. Staging does not execute files, enroll, grant permissions or start units.

Recovery `VerifyStagedBundle` verifies the original publisher/plan binding again,
requires a current-user-owned private stage directory, reads owner-only regular
single-link nonwritable release.json and READY without following links, compares
their exact bytes to the expected manifest/digest, then rehashes selected files.
It makes no writes. The CLI resume path repeats confirmation and current-context
checks and is mutually exclusive with source/staging-parent options. Incomplete
or changed stages fail closed; no automatic repair, deletion or activation.
