# Edge local discovery consent v1

Local state may contain `discovery_plan` (exact confirmed installation plan JSON)
and `discovery_plan_sha256` (SHA-256 of compact JSON bytes, because state JSON
formatting may change whitespace). Both absent means legacy, NOT verified consent.
Only one present, digest mismatch, invalid plan or changed origin/environment
fails closed. Plan expiry governs initial confirmation; durable consent is not
silently revoked when the short-lived installation plan expires.

For a consent-bound device, every signed task must match the registered environment
and be a scan with an explicit selected connector and explicit nonempty roots and
include lists. Each requested root and include must be an exact member of that
connector's confirmed lists. This intentionally does not infer subdirectory or
wildcard containment. Nonempty excludes are rejected until Connector exclusion
behavior is consistently verified. Unknown payload/scope
fields are rejected. Enforcement occurs before ledger reuse or connector startup;
failure produces `discovery_scope_denied`, never runs scanned content.

Developer command `confirm-discovery-plan --plan FILE --tenant ID
--confirm-plan-sha256 DIGEST` requires a private existing registered state and the
task lock, explicit exact raw-file confirmation, current plan, trusted expected
tenant, registered environment/origin and actual Linux architecture. It persists
the local restriction only, with no network, scan, enrollment, policy grant or
assertion that a release is verified. Future installer must independently perform
release verification and use this confirmation boundary in its user flow.

This task-envelope gate does not certify every Connector's internal I/O. File
content reads must independently obey includes; directory entry metadata and
existing secret_ref defenses retain their documented behavior. Hermes metadata
extraction and cursor hashing must not read config.yaml unless included, and must
not follow a config symlink outside the profile. Other Connector conformance and
non-file scope contracts remain pending.

OpenClaw rejects explicit include lists that omit openclaw.json and nonempty
excludes, at both validate_scope and direct collect. Empty legacy include keeps
the documented openclaw.json default; consent-bound Edge tasks require explicit
nonempty include before invoking the Connector.
