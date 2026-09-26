# Enterprise release finalization v1

Linux enterprise_finalize.py consumes an already externally signed release,
candidate directory, explicitly expected full source commit/version and an
independently reviewed native Edge verifier path AND SHA-256. No signer or key
override is offered. A verifier inside the candidate is refused; the caller must
establish the verifier's trust independently, not copy a checksum from untrusted
candidate metadata. The pinned verifier is copied to private temporary storage
before execution. A digest alone is not provenance or authorization.

Require the signed envelope's canonical unsigned content to exactly match the
candidate signing request. Invoke the pinned verifier with --bundle against the
candidate and require the exact successful identity/digest/all-artifact report.
Report field types must match as well: numeric 0/1 do not substitute for booleans;
duplicate or extra keys, malformed output and a nonzero exit fail closed.
Then copy signed artifacts into a private new bundle, checking actual copied
bytes against signed sizes/hashes, and independently verify that staged bundle.
Only afterward create a portable ZIP, release.json, descriptive SOURCE-INFO.json
and SHA256SUMS. ZIP content is checked against the staged files. Output is a new
directory outside the candidate and checkout; no input is overwritten.

Local input directories/ancestors must be stable and trusted. Final file opens
reject symlinks, nonregular/multilink files and size excess; this is not a sandbox
against same-user/root mutation. Copy-time artifact hashes and post-copy verifier
prevent candidate bytes changing into unsigned executable contents. Supporting
license files are copied from reviewed candidate source but are NOT publisher
authenticated by the binary signature. SOURCE-INFO and INSTALL.md are descriptive,
not independent attestations. Missing license files fail assembly. No candidate
key, executable or script is run; only the separately pinned verifier is executed.

No registration, scan, service lifecycle, plan generation, upload, publishing or
installation acceptance is performed. `published=false`, `installed=false`,
`installation_acceptance=not_run`. No final directory is created before verification
and archive success; a final transfer error may leave incomplete output for explicit
review. A signed binary bundle is not yet a fully integrated downloadable Skill
installation workflow. Official signature success remains an external acceptance
gate; mocked assembly tests must never be reported as that gate passing.
